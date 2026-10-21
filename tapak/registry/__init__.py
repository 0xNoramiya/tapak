"""Append-only, hash-chained, Ed25519-signed registry of issued documents and copies.

Modules (import from them directly; this package file stays empty so that
``python -m tapak.registry.signing`` and ``python -m tapak.registry.verify`` run cleanly):

* ``tapak.registry.chain``: the SQLite registry (``Registry``, ``sign_pending``,
  ``registry_from_manifest``, ``describe_entry``, ``canary_token_digest``,
  ``canonical_json``, ``compute_entry_hash``).
* ``tapak.registry.signing``: the Ed25519 key file (``Signer``, ``load_signer``,
  ``generate_signing_key``, ``load_public_key``, ``verify_signature``) and the key
  holder's tool ``python -m tapak.registry.signing generate|sign-pending``.
* ``tapak.registry.verify``: independent verification with only the public key
  (``verify_registry``, console script ``tapak-verify-registry``).
* ``tapak.registry.merkle``: daily Merkle roots (``export_daily_roots``,
  ``check_daily_roots``, ``merkle_root``, ``merkle_proof``, ``verify_proof``).
"""
