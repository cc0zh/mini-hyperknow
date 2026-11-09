----------------------------- MODULE ClassroomFlow ----------------------------
EXTENDS Integers
CONSTANT Broken
VARIABLES phase, cursor
vars == <<phase, cursor>>
Init == /\ phase = "unprepared" /\ cursor = -1
Prepare == /\ phase = "unprepared" /\ phase' = "queued" /\ UNCHANGED cursor
Start == /\ phase = "queued" /\ phase' = "generating" /\ UNCHANGED cursor
SaveScript == /\ phase = "generating" /\ phase' = "paused" /\ cursor' = -1
Play == /\ phase = "paused" /\ phase' = "playing" /\ UNCHANGED cursor
Pause == /\ phase = "playing" /\ phase' = "paused" /\ UNCHANGED cursor
Advance == /\ phase \in {"paused", "playing"} /\ cursor < 2 /\ cursor' = cursor + 1
           /\ phase' = IF cursor + 1 = 1 THEN "paused" ELSE phase
Ask == /\ phase \in {"paused", "playing"} /\ cursor >= 0 /\ phase' = "answering" /\ UNCHANGED cursor
Answer == /\ phase = "answering" /\ phase' = "paused" /\ UNCHANGED cursor
Complete == /\ phase \in {"paused", "playing"} /\ (Broken \/ cursor = 2)
            /\ phase' = "completed" /\ UNCHANGED cursor
Refresh == /\ phase = "playing" /\ phase' = "paused" /\ UNCHANGED cursor
Cancel == /\ phase \in {"queued", "generating"} /\ phase' = "cancelled" /\ UNCHANGED cursor
Fail == /\ phase = "generating" /\ phase' = "failed" /\ UNCHANGED cursor
Restart == /\ phase \in {"queued", "generating"} /\ phase' = "interrupted" /\ UNCHANGED cursor
Retry == /\ phase \in {"failed", "cancelled", "interrupted"} /\ phase' = "queued" /\ UNCHANGED cursor
Done == /\ phase = "completed" /\ UNCHANGED vars
Next == Prepare \/ Start \/ SaveScript \/ Play \/ Pause \/ Advance \/ Ask \/ Answer \/ Complete \/ Refresh \/ Cancel \/ Fail \/ Restart \/ Retry \/ Done
CompletionRequiresSummary == phase = "completed" => cursor = 2
Spec == Init /\ [][Next]_vars
=============================================================================
