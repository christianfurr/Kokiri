"""Typed development grammar shared by single actions and bounded scenarios."""
import math
import re

from kokiri import KokiriError

BUTTONS = {"a","b","x","y","l","r","zl","zr","plus","minus","l3","r3","left","up","right","down"}
DESTINATIONS = {"field", "kokiri", "kakariko", "crater"}
SETTINGS = {"graphics-hud-position.txt": {"top-left","top-right","bottom-left","bottom-right"},
            "graphics-hud-scale.txt": {75,100,125,150}, "graphics-overlay.txt": {0,1,2},
            "graphics-canvas.txt": {0,1,2,3,4}, "graphics-frame.txt": {"off","lock-30","lock-60"}}


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise KokiriError("A numeric action value is outside its finite bounds.")
    return value


def milliseconds(value):
    if type(value) is not int or not 1 <= value <= 5000:
        raise KokiriError("Input duration must be1–5000milliseconds.")
    return value


def action(step: dict) -> tuple[str, str, float]:
    if not isinstance(step, dict):
        raise KokiriError("Each scenario step must be a typed action object.")
    kind = step.get("action")
    fields = {"position": set(), "button": {"button","milliseconds"},
              "stick": {"stick","x","y","milliseconds"}, "warp": {"destination"},
              "move": {"map","x","y","z"}, "settings": {"page"}, "wait": {"milliseconds"},
              "checkpoint": {"label"}, "capture": {"label"}}
    if not isinstance(kind,str) or kind not in fields or set(step) != fields[kind] | {"action"}:
        raise KokiriError("Choose a typed action with exactly its documented fields.")
    if kind == "position": return kind, "", 10
    if kind == "button":
        if not isinstance(step["button"],str) or step["button"] not in BUTTONS: raise KokiriError("Unsupported game button.")
        ms=milliseconds(step["milliseconds"]); return kind, f"{step['button']} {ms}", ms/1000+5
    if kind == "stick":
        if step["stick"] not in ("left","right"): raise KokiriError("Choose the left or right stick.")
        x=number(step["x"],-1,1);y=number(step["y"],-1,1);ms=milliseconds(step["milliseconds"])
        return kind, f"{step['stick']} {x:.6f} {y:.6f} {ms}", ms/1000+5
    if kind == "warp":
        if not isinstance(step["destination"],str) or step["destination"] not in DESTINATIONS: raise KokiriError("Choose a supported named destination.")
        return kind, step["destination"], 190
    if kind == "move":
        if not isinstance(step["map"],str) or not re.fullmatch(r"[A-Za-z0-9_]{1,63}",step["map"]): raise KokiriError("Use an observed area identifier.")
        xyz=[number(step[key],-9999,9999) for key in ("x","y","z")]
        return kind, step["map"]+" "+" ".join(f"{v:.6f}" for v in xyz),10
    if kind == "settings":
        if type(step["page"]) is not int or not -1<=step["page"]<=4: raise KokiriError("Settings pages are-1(closed) through4.")
        return kind,str(step["page"]),5
    if kind == "wait":
        ms=milliseconds(step["milliseconds"]); return kind,str(ms),ms/1000
    if not isinstance(step["label"],str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,64}",step["label"]): raise KokiriError("Use a bounded plain checkpoint label.")
    return kind,step["label"],10 if kind=="capture" else 0


def scenario(steps: list) -> list[tuple[str,str,float]]:
    if not isinstance(steps,list) or not 1<=len(steps)<=64:
        raise KokiriError("A scenario contains1–64typed steps.")
    actions=[action(step) for step in steps]
    if sum(step[2] for step in actions)>300:
        raise KokiriError("The complete scenario exceeds its300second execution bound.")
    return actions
