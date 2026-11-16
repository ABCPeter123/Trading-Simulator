"""Exact historical checkpoint snapshots, independent of current active state.

Checkpoints are read-only. Rewinding does not reverse or alter trades. A new
simulator step records one compact checkpoint. Existing saves begin recording
from the moment they are next modified (earlier exact states unavailable).
"""
from copy import deepcopy
from fastapi import HTTPException

CORE = ("cash","qty","avg","realized","positions","orders","strategy",
        "risk","completed","events")
MAX_CHECKPOINTS = 1500

def checkpoint(state):
    stamp = {
        "index":state["index"],
        "fills_count":len(state["fills"]),
        "curve_count":len(state["curve"]),
    }
    for key in CORE:
        if key in state:
            stamp[key]=deepcopy(state[key])
    snapshots=state.setdefault("checkpoints",[])
    if snapshots and snapshots[-1]["index"] == stamp["index"]:
        snapshots[-1]=stamp
    else:
        snapshots.append(stamp)
        if len(snapshots) > MAX_CHECKPOINTS:
            del snapshots[:len(snapshots)-MAX_CHECKPOINTS]

def snapshot_at(state, requested_index):
    matches = (step for step in state.get("checkpoints",[])
               if step["index"] == requested_index)
    cp = next(matches,None)
    if cp is None:
        raise HTTPException(422, detail="No exact saved checkpoint at that historical step.")
    reconstructed=deepcopy(state)
    for key in CORE:
        if key in cp:
            reconstructed[key]=deepcopy(cp[key])
        else:
            reconstructed.pop(key,None)
    reconstructed["index"]=requested_index
    reconstructed["fills"]=deepcopy(state["fills"][:cp["fills_count"]])
    reconstructed["curve"]=deepcopy(state["curve"][:cp["curve_count"]])
    return reconstructed

def history_info(state):
    checkpoints=state.get("checkpoints") or []
    return {"history_start":checkpoints[0]["index"] if checkpoints else state["index"],
            "live_index":state["index"],
            "checkpoint_count":len(checkpoints)}
