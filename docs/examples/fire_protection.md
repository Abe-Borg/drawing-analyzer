---
name: fire-protection
title: Fire Protection — NFPA 13 (2022 edition) sprinkler QC
disciplines: F, FP, SP, FS
version: 1
author: Abraham Borg
date: 2026-07-08
nfpa_13_edition: "2022"
---

# Fire Protection review checklist — written against NFPA 13, 2022 edition

> **Which edition this is.** Every section number below is from **NFPA 13,
> 2022 edition**. The current edition is **2025**, and these citations have
> **not** been re-verified against it. NFPA 13 renumbers between editions — the
> 2019 reorganization is the reason one of the checks below exists — so a 2022
> section number carried into a 2025 review is exactly the error this checklist
> is meant to catch. Before using this on a live project, re-verify each cited
> section against the edition the set actually adopts, and update the two
> statements above together (the title and this note) so the file never claims
> an edition it was not checked against.

A senior fire-protection engineer's back-check for an NFPA 13 sprinkler set.
Each item is one check; apply it against the schedules, general notes, and plans
on the sheet. Verify every section number against the edition the set actually
adopts (harvest it from the general notes — the app's identity stage does this
and reports the adopted edition, and the edition audit flags a cited edition
that diverges from the adopted one).

- Dry-pipe and double-interlock preaction (DIPA) systems carry a +30% increase on the remote design area relative to the wet-system base curve; flag any dry or DIPA schedule row whose remote area equals the wet-system base area (no increase applied). [high] (NFPA 13 2022 §19.2.3.2.5)
- Extra-hazard or storage densities at or above 0.20 gpm/ft² call for K-8.0 or larger orifice sprinklers; flag any such row that specifies a smaller K-factor. [high] (NFPA 13 Ch. 9, K-factor selection)
- Extra-hazard standard-spray coverage is limited to 100 ft² per sprinkler; flag an EH row whose maximum coverage area exceeds 100 ft². [medium] (NFPA 13 Ch. 10 coverage tables)
- Light-hazard systems on new work require quick-response sprinklers; flag any light-hazard row that specifies STANDARD response. [medium] (NFPA 13 quick-response requirement)
- Wet-system relief valves must be set at 175 psi, or the maximum system pressure plus 10 psi, whichever is greater; flag a relief-valve note set below that. [medium] (NFPA 13 2022 §8.1.2)
- The same space type must not appear under two different hazard classifications on the same sheet without an explicit reason; flag a room/area that is classified inconsistently. [medium]
- NFPA 13 citations using pre-2019 numbering are stale (e.g. "Table 13.2.1" or "Chapter 13 misc storage" map to §4.3.1.7 and Chapters 20–25 in the 2019+ reorganization); flag a note that cites the old numbering. [low]
- An FDC (fire department connection) signage note must name the actual area or system the FDC serves on this sheet; flag a generic or copy-pasted FDC sign that names the wrong area. [medium]
- Every dry, preaction, or DIPA system must show or reference its inspector's test valve (ITV), air supply / air compressor, low-point drains, and gauge locations; flag a dry/preaction system missing any of these (an absence — phrase it "expected X; not found on this sheet"). [medium]
