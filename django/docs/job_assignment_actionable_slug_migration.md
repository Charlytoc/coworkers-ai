# Job assignment actionable slug renames (one-shot)

Reply-on-thread actions were renamed; existing `JobAssignment.config` JSON in the database must be updated.

## Rewrites

In each job’s `config.actions[*].actionable_slug`:

| Old slug               | New slug            |
|------------------------|---------------------|
| `telegram.send_message` | `telegram.reply_dm` |
| `instagram.send_message` | `instagram.reply_dm` |

No schema change beyond the string; `direct_dm_recipients` is only used by the new `*.send_direct_dm` actions.

## Django data migration (you run it)

1. `python manage.py makemigrations core --empty -n rewrite_dm_actionable_slugs`
2. In the generated migration’s `RunPython`, replace job configs in a forward function, e.g.:

```python
def forwards(apps, schema_editor):
    JobAssignment = apps.get_model("core", "JobAssignment")
    for job in JobAssignment.objects.iterator():
        cfg = job.config or {}
        actions = cfg.get("actions") or []
        changed = False
        for row in actions:
            if not isinstance(row, dict):
                continue
            slug = row.get("actionable_slug")
            if slug == "telegram.send_message":
                row["actionable_slug"] = "telegram.reply_dm"
                changed = True
            elif slug == "instagram.send_message":
                row["actionable_slug"] = "instagram.reply_dm"
                changed = True
        if changed:
            job.config = cfg
            job.save(update_fields=["config", "modified"])
```

3. `python manage.py migrate`

Adjust the app label if your historical app name differs.
