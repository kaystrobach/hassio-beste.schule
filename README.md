# beste.schule for Home Assistant

A Home Assistant **custom integration** (no add-on, no Docker, no MQTT
required) that polls [beste.schule](https://beste.schule) once a day per
child and exposes:

- Sensors with markdown-formatted **grade tables**, **final-grade
  tables** and a **journal feed** in their attributes.
- A numeric **overall average** sensor with proper long-term statistics.
- **Native HA events** (`besteschule_grade_added`, `..._changed`,
  `..._removed`, `besteschule_grades_updated`) so you can build any
  notification automation you like.

It runs inside the HA Python process — no Supervisor, so it works on HA
Core, HA Container, HA Supervised and HA OS alike.

## Install (via HACS — recommended)

1. In HACS, open **⋮ → Custom repositories** and add this repo URL with
   category **Integration**.
2. Find **beste.schule** in HACS, install it.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → beste.schule**.

## Install (manual)

Copy `custom_components/besteschule/` into your HA `<config>/custom_components/`
folder and restart HA. Then add the integration as above.

## Setup

You need a **Personal Access Token** from beste.schule:

1. Log in at <https://beste.schule>.
2. Top-right → click your name → **Benutzerkonto**.
3. Tab **API** → bottom of the page → **Personal Access Token** → copy it.

Paste the token into the integration's setup wizard. If your token sees
multiple students (typical for guardians with several children), the
wizard asks which one this entry should track.

### Multiple children / multiple accounts

Just **add the integration again** for each child or each token. Every
entry runs its own coordinator, has its own sensors, fires its own
events. That's the native multi-instance support config-flow gives us
for free — no special configuration on your side.

## What you get

For an entry whose student is named "Lina", these entities appear under
a single device "beste.schule – Lina":

| Entity | Native value | Attributes |
| --- | --- | --- |
| `sensor.besteschule_lina_noten` | grade count | `markdown`, `grades`, `average`, `updated_at` |
| `sensor.besteschule_lina_notendurchschnitt` | numeric average | `updated_at` |
| `sensor.besteschule_lina_endnoten` | finalgrade count | `markdown`, `finalgrades`, `updated_at` |
| `sensor.besteschule_lina_klassenbuch` | journal entry count | `markdown`, `days`, `updated_at` |
| `sensor.besteschule_lina_letzte_aktualisierung` | ISO timestamp | — |

(Entity ids are German because the entity names are; HA derives them
from the translated names. They will follow your HA UI language.)

### Show the markdown table on a dashboard

```yaml
type: markdown
content: "{{ state_attr('sensor.besteschule_lina_noten', 'markdown') }}"
```

Same for `endnoten` and `klassenbuch`.

## Events

Fired on the HA event bus whenever the daily refresh detects a change:

| Event | Payload |
| --- | --- |
| `besteschule_grade_added` | `entry_id`, `student_id`, `student`, plus the new grade's `subject_name`, `value`, `given_at`, `collection`, `teacher` |
| `besteschule_grade_changed` | `entry_id`, `student_id`, `student`, `old`, `new` |
| `besteschule_grade_removed` | `entry_id`, `student_id`, `student`, plus the removed grade's signature |
| `besteschule_grades_updated` | `entry_id`, `student_id`, `student`, `added`, `changed`, `removed` (counts) |

### Example automation

```yaml
alias: "Push notification for new grades"
trigger:
  - platform: event
    event_type: besteschule_grade_added
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "Neue Note für {{ trigger.event.data.student }}"
      message: >
        {{ trigger.event.data.subject_name }}:
        {{ trigger.event.data.value }}
        ({{ trigger.event.data.collection }})
```

To target a single child, filter with `event_data:`:

```yaml
trigger:
  - platform: event
    event_type: besteschule_grade_added
    event_data:
      student_id: 12345
```

## Options

After setup, click **Configure** on the integration tile to change:

- **Refresh every (hours)** — default 24, range 1–168.
- **Journal lookback (days)** — default 14, set to 0 to skip the journal
  entirely.

## Manual refresh

Use the built-in `homeassistant.update_entity` service on any of this
integration's sensors — that triggers an immediate fetch.

## Privacy

State is stored in HA's normal storage (`<config>/.storage/`). Outbound
traffic only goes to `https://beste.schule`. No third party touches the
data.
