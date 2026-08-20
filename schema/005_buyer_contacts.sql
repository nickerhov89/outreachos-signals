-- Migration 005: add buyer_contacts_json to signal_classifications
-- Stores enriched contacts (role, name, email, status) per classified event
ALTER TABLE signal_classifications ADD COLUMN buyer_contacts_json TEXT;
