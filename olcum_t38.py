import json
import sys
import time
from pathlib import Path

sys.path.insert(0, 'araclar')
import gorev_baglam as g
import jev_client

vault, inputs, output = sys.argv[1:]
rows = [json.loads(line) for line in Path(inputs).read_text().splitlines()]
results = []
with jev_client.disabled():
 for row in rows:
  start = time.monotonic()
  p = g.build_task_package(vault, row['prompt'], cwd=row.get('cwd'), budget=2000)
  results.append(dict(id=row['id'], project_id=p.get('project_id'),
      selected_ids=p.get('selected_ids'), elapsed_ms=round((time.monotonic()-start)*1000, 2)))
Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
print('Replayed:', len(results))
