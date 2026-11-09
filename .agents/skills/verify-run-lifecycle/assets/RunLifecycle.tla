----------------------------- MODULE RunLifecycle -----------------------------
EXTENDS Naturals
CONSTANT Broken
VARIABLES phase, receipt, conflictingReply, retries
vars == <<phase, receipt, conflictingReply, retries>>
Init == /\ phase = "new" /\ receipt = 0 /\ conflictingReply = FALSE /\ retries = 0
Create == /\ phase = "new" /\ receipt' \in {1, 2} /\ phase' = "queued"
          /\ UNCHANGED <<conflictingReply, retries>>
Start == /\ phase = "queued" /\ phase' = "generating"
         /\ UNCHANGED <<receipt, conflictingReply, retries>>
Finish == /\ phase = "generating" /\ phase' = "ready"
          /\ UNCHANGED <<receipt, conflictingReply, retries>>
ReplaySame == /\ receipt # 0 /\ UNCHANGED vars
ReplayDifferent == /\ receipt # 0 /\ conflictingReply' = Broken
                   /\ UNCHANGED <<phase, receipt, retries>>
Cancel == /\ phase \in {"queued", "generating"} /\ phase' = "cancelled"
          /\ UNCHANGED <<receipt, conflictingReply, retries>>
Fail == /\ phase = "generating" /\ phase' = "failed"
        /\ UNCHANGED <<receipt, conflictingReply, retries>>
Restart == /\ phase \in {"queued", "generating"} /\ phase' = "interrupted"
           /\ UNCHANGED <<receipt, conflictingReply, retries>>
Retry == /\ phase \in {"cancelled", "failed", "interrupted"} /\ retries = 0
         /\ retries' = 1 /\ phase' = "queued"
         /\ UNCHANGED <<receipt, conflictingReply>>
Done == /\ phase \in {"ready", "cancelled", "failed", "interrupted"} /\ UNCHANGED vars
Next == Create \/ Start \/ Finish \/ ReplaySame \/ ReplayDifferent \/ Cancel \/ Fail \/ Restart \/ Retry \/ Done
NoConflictingReplay == ~conflictingReply
Spec == Init /\ [][Next]_vars
=============================================================================
