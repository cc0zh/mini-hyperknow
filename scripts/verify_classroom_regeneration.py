"""Reject old-script questions while regeneration is active, even with a newer teacher run."""

from pathlib import Path
import json
import sqlite3
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

from hyperknow.domain import AppError
from hyperknow.lesson_domain import BoardScriptDraft
from test_lesson import script_input
import test_lesson_structure as lesson_fixtures


class RegenerationIsolationTests(unittest.TestCase):
    def test_new_teacher_run_cannot_hide_regeneration(self):
        fixture = lesson_fixtures.CompleteLessonStorageTests(
            'test_early_exit_never_completes_but_final_summary_can')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        db, session_id = fixture.db, fixture.sid
        original = fixture.ready()
        pending = db.regenerate_lesson(session_id, {
            'client_command_id': 'probe-regenerate',
            'expected_version': original['progress']['version'],
        }, 'stored-model', True)
        regeneration = pending['generation_run']
        with self.assertRaises(AppError) as blocked:
            db.ask_question(session_id, fixture.command(
                pending, 'probe-before-teacher', cursor=-1,
                question='旧讲义问题', was_playing=False), 'stored-model', True)
        self.assertEqual(blocked.exception.code, 'lesson_generation_active')
        try:
            teacher = db.prepare_teacher_lesson(
                session_id, 'probe-prepare-teacher', 'stored-model', True)
        except AppError as error:
            self.assertEqual(error.status, 409)
            self.assertEqual(error.code, 'lesson_generation_active')
            self.assertEqual(db.get_lesson(session_id)['interactions'], [])
            print('REGENERATION_GUARD_PASS teacher preparation rejected', flush=True)
            return
        try:
            asked = db.ask_question(session_id, fixture.command(
                teacher, 'probe-after-teacher', cursor=-1,
                question='旧讲义问题', was_playing=False), 'stored-model', True)
        except AppError as error:
            self.assertEqual(error.code, 'lesson_generation_active')
            self.assertEqual(db.get_lesson(session_id)['interactions'], [])
            print('REGENERATION_GUARD_PASS old-script question rejected', flush=True)
            return
        self.assertEqual(asked['interactions'][0]['status'], 'pending')
        db.transition(regeneration['run_id'], {'queued'}, status='generating')
        db.finish_lesson(regeneration['run_id'], BoardScriptDraft.model_validate(script_input()))
        after = db.get_lesson(session_id)
        self.assertNotEqual(after['script']['script_id'], original['script']['script_id'])
        self.assertEqual(after['interactions'], [])
        connection = sqlite3.connect(fixture.path)
        try:
            stored_questions = connection.execute('SELECT COUNT(*) FROM lesson_interactions').fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(stored_questions, 1)
        observations = {
            'outcome': 'bug',
            'introduced_commit': 'e42d4cfe5eb79bec9e03ee18794328a6fd295038',
            'teacher_run_kind': teacher['generation_run']['kind'],
            'question_admitted_during_regeneration': True,
            'script_replaced': after['script']['script_id'] != original['script']['script_id'],
            'visible_interactions_after_replacement': len(after['interactions']),
            'stored_interactions_after_replacement': stored_questions,
        }
        print('REGENERATION_GUARD_BUG ' + json.dumps(observations), flush=True)
        self.fail('Old-script question was accepted during regeneration and can disappear after replacement')


if __name__ == '__main__':
    unittest.main(verbosity=2)
