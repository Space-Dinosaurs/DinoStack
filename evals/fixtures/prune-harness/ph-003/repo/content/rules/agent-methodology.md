# agent-methodology

## Worker preamble
Before executing any task, Workers must read the execution contract
block in their spawn prompt. The outputs field names the artifact to
produce; the tool_scope field documents permitted tools.


## Loop control
Loops cap at 3 iterations unless the ticket declares otherwise.
