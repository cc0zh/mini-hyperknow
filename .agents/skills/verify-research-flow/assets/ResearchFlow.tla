----------------------------- MODULE ResearchFlow -----------------------------
EXTENDS Naturals
CONSTANT Broken
VARIABLES phase, steps, searched, pageRead
vars == <<phase, steps, searched, pageRead>>
Init == /\ phase = "queued" /\ steps = 0 /\ searched = FALSE /\ pageRead = FALSE
Start == /\ phase = "queued" /\ phase' = "generating" /\ UNCHANGED <<steps, searched, pageRead>>
BudgetAvailable == steps < (IF Broken THEN 11 ELSE 10)
Search == /\ phase = "generating" /\ BudgetAvailable /\ steps' = steps + 1 /\ searched' = TRUE /\ UNCHANGED <<phase, pageRead>>
SearchFails == /\ phase = "generating" /\ BudgetAvailable /\ steps' = steps + 1 /\ UNCHANGED <<phase, searched, pageRead>>
ReadPage == /\ phase = "generating" /\ BudgetAvailable /\ steps' = steps + 1 /\ pageRead' = TRUE /\ UNCHANGED <<phase, searched>>
Finish == /\ phase = "generating" /\ searched /\ pageRead /\ phase' = "ready" /\ UNCHANGED <<steps, searched, pageRead>>
Cancel == /\ phase \in {"queued", "generating"} /\ phase' = "cancelled" /\ UNCHANGED <<steps, searched, pageRead>>
Fail == /\ phase = "generating" /\ phase' = "failed" /\ UNCHANGED <<steps, searched, pageRead>>
Restart == /\ phase \in {"queued", "generating"} /\ phase' = "interrupted" /\ UNCHANGED <<steps, searched, pageRead>>
Done == /\ phase \in {"ready", "cancelled", "failed", "interrupted"} /\ UNCHANGED vars
Next == Start \/ Search \/ SearchFails \/ ReadPage \/ Finish \/ Cancel \/ Fail \/ Restart \/ Done
ToolBudgetRespected == steps <= 10
Spec == Init /\ [][Next]_vars
=============================================================================
