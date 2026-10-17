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
| sex | "female only", "men only", "solo mujeres" | caution | 100.75(c)(1); HUD 1995 allows a sex preference only for shared living quarters, which many room rentals are, so the owner decides |
| sex | "no gays", "straight only" | caution | Federal treatment of sexual orientation and gender identity as sex discrimination under the Act has changed over time; many state and local laws protect them, so the phrase is always flagged |
| source_of_income | "no Section 8", "no vouchers", "no housing assistance" | caution, or violation when `policy.source_of_income_protected` is true | Not covered by 24 CFR 100.75; protected only by some state and local laws, so the world policy decides |

Each finding returns `{phrase, rule, severity, citation, suggestion}`. `ok` is false when any finding is a violation; cautions are advisory and do not block publishing.

## What is deliberately allowed

Occupancy limits ("maximum 2 occupants"), "no pets", "no smoking", property facts ("second-floor walk-up", "shared bath") and landmarks ("near Duke Chapel") are not flagged.
