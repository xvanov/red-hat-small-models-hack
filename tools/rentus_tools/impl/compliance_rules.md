# Fair-housing phrase rules (check_listing_compliance)

`check_listing_compliance` and `publish_listing` run a deterministic phrase list over listing text. No model is involved. The rules live in `compliance.py`; this file says where each one comes from. It is a screening aid for a sandbox demo, not legal advice.

## Sources

- **24 CFR 100.75**, "Discriminatory advertisements, statements and notices" (HUD's Fair Housing Act regulations). §100.75(a) makes it unlawful to make, print or publish any notice, statement or advertisement for the sale or rental of a dwelling that indicates any preference, limitation or discrimination because of race, color, religion, sex, handicap, familial status or national origin. §100.75(c) lists prohibited practices, including (c)(1) words, phrases, symbols or forms that convey that dwellings are or are not available to a particular group, (c)(2) words that express a preference for or limitation on any buyer or renter, and (c)(3) selecting media or locations that deny information to a group. https://www.ecfr.gov/current/title-24/subtitle-B/chapter-I/subchapter-A/part-100/subpart-B/section-100.75
- **42 U.S.C. 3604(c)**, the statute the regulation implements.
- **HUD, "Guidance Regarding Advertisements Under §804(c) of the Fair Housing Act"** (Roberta Achtenberg memo, January 9, 1995). It lists words that are and are not acceptable: "adults only", "no children", religious descriptions of a home ("Christian home") and descriptions of the renter rather than the property are problems; descriptions of the property ("walk-up", "no pets", "near a church" as a landmark) are fine; for shared living quarters a sex preference may be stated.

## Rules

| Rule | Example phrases flagged | Severity | Basis |
|---|---|---|---|
| familial_status | "no kids", "no children", "adults only", "no families", "ideal for single professionals", "perfect for couples", "singles only", "mature couple", "sin niños", "solo adultos" | violation | 100.75(c)(1)-(2); HUD 1995 ("adults only", "no children"; describe the property, not the renter) |
| religion | "Christian home", "Catholic household", "Muslims only", "no Jews", "church-going", "hogar cristiano" | violation | 100.75(c)(1); HUD 1995 (religious preference) |
| race_color_national_origin | "whites only", "no Hispanics", "must speak English", "Americans only", "US citizens only" | violation | 100.75(c)(1),(c)(3) |
| race_color_national_origin | "exclusive neighborhood", "ethnic neighborhood" | caution | HUD 1995 lists "exclusive" among words that can convey a racial preference depending on context |
| handicap | "no wheelchairs", "able-bodied", "must be able to climb stairs", "no mental illness", "no service animals", "no emotional support animals" | violation | 100.75(c)(1); HUD 1995 (describe accessibility of the property, not abilities of the renter); assistance animals are not pets |
| sex | "females only", "males only", "men only", "female roommates only", "solo mujeres" | warning (`owner_decides: true`) | 100.75(c)(1); HUD 1995 allows a sex preference only for shared living quarters. Every room in this inventory is a room in a shared home, so the phrase is surfaced for the owner to approve or remove and never blocks publishing (owner decision D23) |
| sex | "no gays", "straight only" | caution | Federal treatment of sexual orientation and gender identity as sex discrimination under the Act has changed over time; many state and local laws protect them, so the phrase is always flagged |
| source_of_income | "no Section 8", "no vouchers", "no housing assistance" | caution, or violation when `policy.source_of_income_protected` is true | Not covered by 24 CFR 100.75; protected only by some state and local laws, so the world policy decides |

Each finding returns `{phrase, rule, severity, citation, suggestion}`, plus `owner_decides: true` on a warning. `ok` is false when any finding is a violation; cautions and warnings are advisory and do not block publishing.

## Gender wording in shared-room listings (owner decision D23, 2026-10-17)

"Males only" / "females only" and similar phrases come back as a `warning`, not a `violation`. The reason is the shared-housing context: the Fair Housing Act's advertising rule (42 U.S.C. 3604(c), 24 CFR 100.75) bars sex preferences in ads, but HUD's 1995 advertising guidance says a sex preference may be stated for shared living quarters, and courts have read the Act as not reaching roommate selection in a shared dwelling (*Fair Housing Council v. Roommate.com*, 9th Cir. 2012). Every room here is a room in a shared home, so the owner decides whether to keep the phrase; the tool flags it and does not block. The check sees only text, so it cannot tell a shared room from a whole unit: for a self-contained unit the phrase should be removed. State and local laws can be stricter. Every other protected-class phrase (familial status, religion, race, color, national origin, handicap) still blocks publishing. This is a screening aid, not legal advice.

## What is deliberately allowed

Occupancy limits ("maximum 2 occupants"), "no pets", "no smoking", property facts ("second-floor walk-up", "shared bath") and landmarks ("near Duke Chapel") are not flagged.
