# Privacy

What upstream-onehealth knows about people, who can see it, and what you can ask us to
remove. This is written for volunteers and residents first, and for data protection
officers second.

## If you volunteer

**What you share:**

- **A name you choose.** It can be a nickname. We never ask for your real name, email or
  phone number.
- **A rough area and the hours you are free.** The area is a neighbourhood-sized box,
  about a kilometre across. It lets us offer you checks near you. It is never your
  exact position.
- **Your location: never.** The mission app does not read your phone's location, even
  when you accept a mission. A mission tells you where to go; it does not track you
  going there.
- **Push notifications, if you allow them.** Your browser gives us an address to send
  "a mission is nearby" to. We store that address and nothing else about your device.

**What you send when you report or complete a mission:**

- the drain point, what you saw or what the test strip showed, and the time;
- your volunteer name;
- a photo, if you add one.

**Who sees it:**

- **The public** (the console, the belief replay, the public-health page) sees *what* was
  observed, *where* and *when*. It never sees *who* reported it, or your photo.
- **Officers and the environmental agency** see your volunteer name next to your report.
  They need it to judge how much to trust a report and to follow up.

## Photos

Nothing in this version checks photos for faces or number plates automatically. So no
photo is shown publicly, ever. Only officers and the agency can open one. If automatic
screening is added later, a photo will still only become public after it has passed.

## Health data never leaves the health zone

Upstream works next to a public-health service, which holds counts of people with
symptoms such as diarrhoea. That service is a separate system: its own database, its
own credentials, its own container. It holds **counts per area per day** and nothing
about any individual person. A count smaller than five cannot be stored at all.

**What crosses between the two systems:**

| Direction | What | What never crosses |
|---|---|---|
| Environmental → health | For each active episode: which areas may have been exposed, when, and by which pathway (for example recreation or irrigation) | Anything about a person |
| Health → environmental | A **test result**: area, syndrome, method, p-value, effect size, number of days, time computed | Counts, cases, patients, anything below area level |
| Health → environmental | A **request to search upstream**: area, syndrome, day, p-value, method | The same |

Every health-facing output says: *"Environmental context, not a diagnosis."*
Upstream never contacts patients, never issues health advisories, and never names a
polluter. Its reports suggest places to inspect.

**Legal basis (GDPR Article 9).** Symptom counts are data concerning health. The
separation above is designed so that such data is processed only by the public-health
authority, under its public-health mandate (Article 9(2)(i)). The environmental system
processes no health data at all, only a statistical answer about an area.

A pilot must confirm this basis with the authority's data protection officer. It is a
design intention, not legal advice.

## Research exports

Researchers can receive the data as Parquet files: episodes, and the observations
behind them. In those files:

- your volunteer name is replaced by a **keyed code**. The same volunteer always gets
  the same code, so a researcher can see that several reports came from one person,
  but cannot work out who. Without the key, nobody can even check a guessed name;
- photos and mission identifiers (which could lead back to you) are left out entirely;
- retracted observations are kept and marked as retracted, never silently dropped.

## Asking us to delete your data

There are two kinds of data. Deleting them works differently, and it is fair to be
clear about how.

1. **Your volunteer profile: deleted on request.** This is your name, area, hours,
   reliability score and push address. Once it is deleted, you receive no more
   missions and no more notifications. In this version an administrator does this by
   hand; a pilot adds a button in the app.

2. **The observations you already made: kept.** The record of observations is
   append-only. Nothing in it is ever edited or deleted (the system is built this way
   so that every past belief can be reproduced and audited). Your past reports stay,
   under the volunteer name you chose.

   **What we can do:** once your profile is gone, that name is no longer linked to
   anything else we hold. If the name identifies you (for example, your real name),
   ask and an officer will record a *retraction* of those reports. A retraction is a
   new entry that stops the system using a report. It does not erase the original.

   This is also why we suggest choosing a nickname rather than your real name.

## Simulated data

The demo and the benchmarks use invented incidents and invented volunteers
(`vol-sim-01` and so on). They are marked as simulated everywhere, and they are kept in
a separate stream that never mixes with real reports.
