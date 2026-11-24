# Independent annotation protocol

Two people label the same shuffled records independently, without model output. A and B sheets start blank. Record annotator qualifications/relationship to the project and the real date. Do not call a software-generated label an independent human label. Obtain consent before reporting reviewer names; pseudonyms suffice.

For sentiment choose positive, negative, neutral or mixed. Label the writer's overall expressed attitude, not the star rating. For complaint choose yes, no or uncertain: a complaint reports an undesirable issue/failed expectation needing investigation, including factual/mixed reviews. A component mention or praise alone is not a complaint. For aspects, use semicolon-separated battery, brakes, infotainment, transmission, interior, service, hvac, other; allow multiple. Note ambiguity and quote the evidence. Do not diagnose a confirmed hardware defect from a narrative.

Use `scripts/prepare_annotation_pack.py`; it preserves existing completed sheets. Keep development and test assignments from `split_manifest.json`, grouped by base template or exact real text. Public reports are complaint-selected and synthetic records repeat templates. Report their results separately, and obtain real noncomplaint controls before claiming real-world specificity/precision.

Run `scripts/score_annotations.py A.csv B.csv --output agreement.json` only after both sheets are genuinely complete. Discuss disagreement and create a separate adjudicated sheet; retain originals. Freeze rules/settings before scoring the test split. If changes are made after inspecting test cases, declare a development study and collect a new test set.

For recommendation assessment, ask a qualified automotive/service reviewer to score support by quoted evidence, component relevance, appropriateness of proposed investigation, unsupported statements and potentially harmful advice. Use a 1–5 anchored scale and record the actual free-text rationale. A clicked Accept button or a self-entered reviewer name is not automatically expert validation.

For manual/assisted triage, counterbalance order across reviewers and equivalent task batches; record raw task times and correctness. Do not populate any task-time result before a real participant completes the task.
