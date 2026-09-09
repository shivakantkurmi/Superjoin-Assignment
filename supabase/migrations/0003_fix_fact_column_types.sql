-- Fix object_value column type: text is correct for raw string fact values.
-- The original schema used jsonb which rejects plain strings like "INR 125 crore".
alter table facts alter column object_value type text using object_value::text;

-- Fix normalized_value similarly — it stores Decimal string representations.
alter table facts alter column normalized_value type text using normalized_value::text;
