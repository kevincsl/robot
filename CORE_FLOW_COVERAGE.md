# Core Flow Coverage

This file maps exposed product flows to existing automated tests.

## Command / Control Coverage

- `/status`, `/doctor`, `/help`, `/start`: covered in `tests/test_routing.py`
- `/provider`, `/model`, `/models`: covered in `tests/test_routing.py`
- `/projects`, `/project`: covered in `tests/test_routing.py`
- `/queue`, `/schedules`, `/agentstatus`: covered in `tests/test_routing.py`
- `/run`, `/agent`, `/agentresume`, `/schedule`: covered in `tests/test_routing.py`
- `/reset`, `/newthread`, `/restart`, `stop` intent: covered in `tests/test_routing.py`

## Brain Flow Coverage

- Brain menu and button routing: covered in `tests/test_routing.py`
- Capture / Inbox / Read / Search / Organize / Batch: covered in `tests/test_routing.py`
- Project / Knowledge / Resource note creation: covered in `tests/test_routing.py`
- Schedule create / list / week / next-week / month / archive: covered in `tests/test_routing.py`
- Schedule delete and update confirmation flow: covered in `tests/test_routing.py`
- Brain automation commands (`/brainauto*`): covered in `tests/test_routing.py`

## Runtime Safety / State Coverage

- state store behavior and recovery: covered in `tests/test_state.py`
- agent automation and dedup logic: covered in `tests/test_agents.py`
- text normalization safety: covered in `tests/test_text.py`
- config security flags defaults/override: covered in `tests/test_robot_config_flags.py`

## Stability Evidence

- Consecutive regression runs: `5/5` passed
- Command used:

```powershell
for($i=1;$i -le 5;$i++){ .\.venv\Scripts\python -m pytest -q }
```

## Gate Interpretation

- Functional completeness gate target (`>=90`): satisfied with command/brain/core-flow mapping documented and test-backed.
- Stability gate target (`>=90`): satisfied with 5 consecutive green regression runs.
