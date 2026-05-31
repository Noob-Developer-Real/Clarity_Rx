import json
import os

def load_medicine_names():
    # Always find the JSON relative to this file, not the working directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "indian_medicine_data.json")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    medicines = []
    for item in data:
        medicine_name1 = item.get("short_composition1")
        medicine_name2 = item.get("short_composition2")
        if medicine_name1:
            medicines.append(medicine_name1.strip().lower())
        if medicine_name2:
            medicines.append(medicine_name2.strip().lower())

    return list(set(medicines))