# Curated mapping for trucker-friendly pseudo categories -> eBay category IDs
TRUCKER_MAP = {
    "trucker:cb-radios":       ["182172", "40027"],
    "trucker:dash-cams":       ["26405"],      # Cameras & Photo > Vehicle GPS/Acc or Camcorders – adjust
    "trucker:gps-truck":       ["156955"],     # GPS Units – refine as needed
    "trucker:bluetooth-headsets":["80077"],
    "trucker:12v-appliances":  ["150928","20667"],  # Vehicle Power Inverters / Car Electronics Accessories
    "trucker:cargo-straps-tie-downs":["179511"],
    "trucker:work-gloves-ppe": ["182982","75576"],
    "trucker:led-aux-lights":  ["33713"],
    "trucker:truck-interior":  ["33707","50459"],
    "trucker:maintenance-consumables":["33695","179497"], # Wipers / Fluids
    "trucker:power-inverters": ["150928"],
}

def resolve(keys_or_ids: list[str]) -> list[str]:
    ids=[]
    for k in keys_or_ids or []:
        ids.extend(TRUCKER_MAP.get(k,[k]))
    # De-dupe and keep strings
    return list(dict.fromkeys(map(str, ids)))
