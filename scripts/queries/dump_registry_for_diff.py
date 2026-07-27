import json
from vso_query_builder.models import Observatory, Instrument

obs = list(Observatory.objects.values("short_name", "name", "description", "datasource_id"))
inst = []
for i in Instrument.objects.select_related("observatory").all():
    inst.append({
        "obs_short_name": i.observatory.short_name if i.observatory else None,
        "short_name": i.short_name,
        "full_name": i.full_name,
        "description": i.description,
    })
print("REGISTRY_JSON_START")
print(json.dumps({"observatories": obs, "instruments": inst}))
print("REGISTRY_JSON_END")
