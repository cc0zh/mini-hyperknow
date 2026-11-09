----------------------------- MODULE AssistanceFlow ---------------------------
EXTENDS Integers
CONSTANT Broken
VARIABLES phase, drafts, saved, response, requests
vars == <<phase, drafts, saved, response, requests>>
Init == /\ phase = "idle" /\ drafts = -1 /\ saved = 0 /\ response = FALSE /\ requests = 0
Send == /\ phase \in {"idle", "ready"} /\ requests < 2 /\ phase' = "queued" /\ drafts' = -1 /\ saved' = 0 /\ response' = FALSE /\ requests' = requests + 1
Start == /\ phase = "queued" /\ phase' = "generating" /\ UNCHANGED <<drafts, saved, response, requests>>
ReceiveDraft == /\ phase = "generating" /\ drafts = -1 /\ drafts' \in 0..2 /\ UNCHANGED <<phase, saved, response, requests>>
Commit == /\ phase = "generating" /\ drafts >= 0 /\ (Broken \/ drafts <= 1)
          /\ phase' = "ready" /\ saved' = drafts /\ response' = TRUE /\ UNCHANGED <<drafts, requests>>
Cancel == /\ phase \in {"queued", "generating"} /\ phase' = "cancelled" /\ UNCHANGED <<drafts, saved, response, requests>>
Fail == /\ phase = "generating" /\ phase' = "failed" /\ UNCHANGED <<drafts, saved, response, requests>>
Restart == /\ phase \in {"queued", "generating"} /\ phase' = "interrupted" /\ UNCHANGED <<drafts, saved, response, requests>>
Retry == /\ phase \in {"cancelled", "failed", "interrupted"} /\ requests < 2
         /\ phase' = "queued" /\ drafts' = -1 /\ saved' = 0 /\ response' = FALSE /\ requests' = requests + 1
Done == /\ phase \in {"ready", "cancelled", "failed", "interrupted"} /\ UNCHANGED vars
Next == Send \/ Start \/ ReceiveDraft \/ Commit \/ Cancel \/ Fail \/ Restart \/ Retry \/ Done
AtMostOneArtifactPerTurn == saved <= 1
Spec == Init /\ [][Next]_vars
=============================================================================
