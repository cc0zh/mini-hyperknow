------------------------------- MODULE QuizFlow -------------------------------
EXTENDS Naturals
CONSTANT Broken
VARIABLES phase, cursor, answers
vars == <<phase, cursor, answers>>
Init == /\ phase = "unprepared" /\ cursor = 0 /\ answers = 0
Prepare == /\ phase = "unprepared" /\ phase' = "queued" /\ UNCHANGED <<cursor, answers>>
Start == /\ phase = "queued" /\ phase' = "generating" /\ UNCHANGED <<cursor, answers>>
SaveQuiz == /\ phase = "generating" /\ phase' = "ready" /\ UNCHANGED <<cursor, answers>>
BeginAttempt == /\ phase = "ready" /\ phase' = "in_progress" /\ UNCHANGED <<cursor, answers>>
Answer == /\ phase = "in_progress" /\ answers = cursor /\ answers' = answers + 1 /\ UNCHANGED <<phase, cursor>>
NextQuestion == /\ phase = "in_progress" /\ answers > cursor /\ cursor = 0 /\ cursor' = 1 /\ UNCHANGED <<phase, answers>>
Submit == /\ phase = "in_progress" /\ (Broken \/ answers = 2) /\ phase' = "submitted" /\ UNCHANGED <<cursor, answers>>
Cancel == /\ phase \in {"queued", "generating"} /\ phase' = "cancelled" /\ UNCHANGED <<cursor, answers>>
Fail == /\ phase = "generating" /\ phase' = "failed" /\ UNCHANGED <<cursor, answers>>
Restart == /\ phase \in {"queued", "generating"} /\ phase' = "interrupted" /\ UNCHANGED <<cursor, answers>>
Retry == /\ phase \in {"failed", "cancelled", "interrupted"} /\ phase' = "queued" /\ UNCHANGED <<cursor, answers>>
Done == /\ phase = "submitted" /\ UNCHANGED vars
Next == Prepare \/ Start \/ SaveQuiz \/ BeginAttempt \/ Answer \/ NextQuestion \/ Submit \/ Cancel \/ Fail \/ Restart \/ Retry \/ Done
SubmissionRequiresAllAnswers == phase = "submitted" => answers = 2
Spec == Init /\ [][Next]_vars
=============================================================================
