-- Bored Capital Academy — current holder distribution for one ERC-721 collection on Ethereum.
-- Parameter: {{contract}} (text), e.g. 0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d (BAYC)
-- Owner = recipient of each token's most recent transfer. Burn addresses are removed downstream.
-- is_contract = 1 when the owner address is a deployed contract (vaults, escrow, lending, multisigs):
-- those tokens hide the real economic owner.
WITH latest AS (
  SELECT
    token_id,
    "to" AS owner,
    ROW_NUMBER() OVER (PARTITION BY token_id ORDER BY block_number DESC, evt_index DESC) AS rn
  FROM nft.transfers
  WHERE blockchain = 'ethereum'
    AND contract_address = from_hex(regexp_replace(lower('{{contract}}'), '^0x', ''))
),
owners AS (
  SELECT owner, COUNT(*) AS tokens FROM latest WHERE rn = 1 GROUP BY owner
),
contracts AS (
  SELECT DISTINCT address FROM ethereum.creation_traces
  WHERE address IN (SELECT owner FROM owners)
)
SELECT o.owner, o.tokens, CASE WHEN c.address IS NULL THEN 0 ELSE 1 END AS is_contract
FROM owners o
LEFT JOIN contracts c ON c.address = o.owner
ORDER BY o.tokens DESC
