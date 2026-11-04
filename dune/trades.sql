-- Bored Capital Academy — all marketplace trades for one collection over the last N days (Ethereum).
-- Parameters: {{contract}} (text), {{days}} (text, e.g. 30)
SELECT
  block_time,
  CAST(token_id AS varchar) AS token_id,
  buyer,
  seller,
  amount_original,
  currency_symbol,
  amount_usd,
  project,
  tx_hash
FROM nft.trades
WHERE blockchain = 'ethereum'
  AND nft_contract_address = from_hex(regexp_replace(lower('{{contract}}'), '^0x', ''))
  AND block_time >= now() - CAST('{{days}}' AS integer) * INTERVAL '1' DAY
ORDER BY block_time
