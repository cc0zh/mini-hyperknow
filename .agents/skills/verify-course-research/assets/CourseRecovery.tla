------------------------- MODULE CourseRecovery -------------------------
EXTENDS Naturals, FiniteSets
CONSTANT Broken

Units == 1..2
Runs == {"parent", "child"}
Payloads == {"a", "b"}
VARIABLES owner, structureStatus, runStatus, currentUnit, units, snapshots, issued
vars == <<owner, structureStatus, runStatus, currentUnit, units, snapshots, issued>>

Active(r) == /\ owner = r
             /\ runStatus[r] = "generating"
             /\ structureStatus = "expanding"

Init == /\ owner = "parent"
        /\ structureStatus = "expanding"
        /\ runStatus = [r \in Runs |-> IF r = "parent" THEN "generating" ELSE "absent"]
        /\ currentUnit = [r \in Runs |-> 0]
        /\ units = [u \in Units |-> [unit_id |-> u, payload |-> "empty", generation_status |-> "pending"]]
        /\ snapshots = [u \in Units |-> [unit_id |-> u, payload |-> "empty", generation_status |-> "uncommitted"]]
        /\ issued = {}

BeginUnit(r, u) ==
    /\ owner = r /\ runStatus[r] \in {"queued", "generating"}
    /\ structureStatus = "expanding"
    /\ units[u].generation_status = "pending"
    /\ \A previous \in Units : previous < u => units[previous].generation_status = "ready"
    /\ runStatus' = [runStatus EXCEPT ![r] = "generating"]
    /\ currentUnit' = [currentUnit EXCEPT ![r] = u]
    /\ units' = [units EXCEPT ![u].generation_status = "generating"]
    /\ issued' = issued \cup {<<r, u>>}
    /\ UNCHANGED <<owner, structureStatus, snapshots>>

FinishUnit(r, u, p) ==
    /\ <<r, u>> \in issued
    /\ IF Active(r) /\ currentUnit[r] = u /\ units[u].generation_status = "generating"
       THEN LET saved == [unit_id |-> u, payload |-> p, generation_status |-> "ready"]
                updated == [units EXCEPT ![u] = saved]
                allReady == \A v \in Units : updated[v].generation_status = "ready"
            IN /\ units' = updated
               /\ snapshots' = [snapshots EXCEPT ![u] = IF @.generation_status = "uncommitted" THEN saved ELSE @]
               /\ currentUnit' = [currentUnit EXCEPT ![r] = 0]
               /\ structureStatus' = IF allReady THEN "ready" ELSE structureStatus
               /\ runStatus' = IF allReady THEN [runStatus EXCEPT ![r] = "ready"] ELSE runStatus
               /\ UNCHANGED <<owner, issued>>
       ELSE UNCHANGED vars

Stop(r) ==
    /\ owner = r /\ runStatus[r] \in {"queued", "generating"}
    /\ runStatus' = [runStatus EXCEPT ![r] = "stopped"]
    /\ units' = [u \in Units |-> IF units[u].generation_status = "ready" THEN units[u]
                  ELSE [units[u] EXCEPT !.generation_status = "stopped"]]
    /\ UNCHANGED <<owner, structureStatus, currentUnit, snapshots, issued>>

Retry ==
    /\ owner = "parent" /\ runStatus["parent"] = "stopped"
    /\ runStatus["child"] = "absent"
    /\ owner' = "child"
    /\ runStatus' = [runStatus EXCEPT !["child"] = "queued"]
    /\ currentUnit' = [currentUnit EXCEPT !["child"] = 0]
    /\ units' = [u \in Units |-> IF ~Broken /\ units[u].generation_status = "ready" THEN units[u]
                  ELSE [units[u] EXCEPT !.generation_status = "pending"]]
    /\ UNCHANGED <<structureStatus, snapshots, issued>>

Done == /\ \A r \in Runs : runStatus[r] \in {"absent", "ready", "stopped"}
        /\ ~(runStatus["parent"] = "stopped" /\ runStatus["child"] = "absent")
        /\ UNCHANGED vars

Next == (\E r \in Runs, u \in Units : BeginUnit(r, u))
        \/ (\E r \in Runs, u \in Units, p \in Payloads : FinishUnit(r, u, p))
        \/ (\E r \in Runs : Stop(r))
        \/ Retry \/ Done

CommittedUnitsPreserved ==
    \A u \in Units : IF snapshots[u].generation_status = "uncommitted" THEN TRUE
                      ELSE units[u] = snapshots[u] /\ units[u].generation_status = "ready"

Spec == Init /\ [][Next]_vars
=============================================================================
