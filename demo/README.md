# Demo Notes

The supplied starter PDFs live in the local-only `starter-datasets/` directory and are excluded from Git because they are company-provided documents. Run the application locally with those files available to reproduce the evaluation flow.

## Required cases

The deterministic relationship behavior is covered by [`tests/test_relationships.py`](../tests/test_relationships.py):

1. **Corroboration:** equal normalized values for the same subject, predicate, period, and scope.
2. **Contradiction:** different normalized values under the same context.
3. **Contextual reconciliation:** different reporting periods are labeled `RECONCILES`, not `CONTRADICTS`.
4. **Failure:** ungrounded evidence is surfaced as `EVIDENCE_FAILED`; malformed Gemini output becomes `AMBIGUOUS`.

These are generic behavior tests, not filename-specific rules. The local Delhivery and India macroeconomy collections provide realistic documents for the live upload demonstration. Exact natural examples should be recorded here after running extraction with a configured Gemini key, including document name, page, quote, and relationship explanation.

## Suggested local walkthrough

1. Start the backend and frontend using the root README.
2. Upload two or more PDFs from one local collection.
3. Inspect extracted facts and open a fact to view its source quote and page.
4. Review relationship explanations and confidence values.
5. Demonstrate an evidence failure or ambiguous model response using the deterministic tests.