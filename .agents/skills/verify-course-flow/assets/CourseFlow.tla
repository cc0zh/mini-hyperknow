------------------------------ MODULE CourseFlow ------------------------------
EXTENDS Naturals
CONSTANT Broken
VARIABLES phase, finished, active, adjusted
vars == <<phase, finished, active, adjusted>>
Init == /\ phase = "queued" /\ finished = 0 /\ active = FALSE /\ adjusted = FALSE
Start == /\ phase = "queued" /\ phase' = "clarifying" /\ UNCHANGED <<finished, active, adjusted>>
NeedAnswers == /\ phase = "clarifying" /\ phase' = "awaiting_answers" /\ UNCHANGED <<finished, active, adjusted>>
NoQuestions == /\ phase = "clarifying" /\ phase' = "research" /\ UNCHANGED <<finished, active, adjusted>>
Answer == /\ phase = "awaiting_answers" /\ phase' = "research" /\ UNCHANGED <<finished, active, adjusted>>
ResearchDone == /\ phase = "research" /\ phase' = "blueprint" /\ UNCHANGED <<finished, active, adjusted>>
SaveBlueprint == /\ phase = "blueprint" /\ phase' = "awaiting_blueprint" /\ UNCHANGED <<finished, active, adjusted>>
Adjust == /\ phase = "awaiting_blueprint" /\ ~adjusted /\ adjusted' = TRUE /\ phase' = "research" /\ UNCHANGED <<finished, active>>
Approve == /\ phase = "awaiting_blueprint" /\ phase' = "units" /\ UNCHANGED <<finished, active, adjusted>>
BeginUnit == /\ phase = "units" /\ ~active /\ finished < 2 /\ active' = TRUE /\ UNCHANGED <<phase, finished, adjusted>>
FinishUnit == /\ phase = "units" /\ active /\ finished' = finished + 1 /\ active' = FALSE
              /\ phase' = IF Broken \/ finished + 1 = 2 THEN "ready" ELSE "units"
              /\ UNCHANGED adjusted
Cancel == /\ phase \notin {"ready", "cancelled", "failed", "interrupted"} /\ phase' = "cancelled" /\ active' = FALSE /\ UNCHANGED <<finished, adjusted>>
Fail == /\ phase \in {"clarifying", "research", "blueprint", "units"} /\ phase' = "failed" /\ active' = FALSE /\ UNCHANGED <<finished, adjusted>>
Restart == /\ phase \in {"queued", "clarifying", "research", "blueprint", "units"} /\ phase' = "interrupted" /\ active' = FALSE /\ UNCHANGED <<finished, adjusted>>
Done == /\ phase \in {"ready", "cancelled", "failed", "interrupted"} /\ UNCHANGED vars
Next == Start \/ NeedAnswers \/ NoQuestions \/ Answer \/ ResearchDone \/ SaveBlueprint \/ Adjust \/ Approve \/ BeginUnit \/ FinishUnit \/ Cancel \/ Fail \/ Restart \/ Done
ReadyRequiresAllUnits == phase = "ready" => finished = 2
Spec == Init /\ [][Next]_vars
=============================================================================
