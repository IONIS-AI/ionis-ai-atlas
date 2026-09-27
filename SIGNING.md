# Signing

Every image published under `docker.io/ki7mt/` is signed with [cosign](https://docs.sigstore.dev/cosign/).
The signing keys live in HashiCorp Vault's transit engine and are **non-exportable**: Vault performs
the ECDSA operation and returns a signature, so no private key exists on any build machine. A stolen
registry credential can push an image; it cannot sign one.

## Verify a release

```sh
cosign verify --key ki7mt-images.pub docker.io/ki7mt/ionis-ai-atlas:0.1.1
cosign verify --key ki7mt-images.pub docker.io/ki7mt/ionis-ai-atlas-db:0.1.1
```

`keys/ki7mt-images.pub` is in this repository. Nothing else is required — no Vault, no credentials,
no account. Verification of a release works offline: the transparency-log entry is bundled with the
signature when it is created, so `--offline` verifies without contacting Sigstore.

One signature covers **both architectures and the attestations**. It is made over the multi-arch
index, and the index references each architecture's image and each attestation manifest by digest:

```
sha256:98c49f68f4cf…  linux/amd64        image
sha256:fcababa08c45…  linux/arm64        image
sha256:1ef8f95eb8c4…  unknown/unknown    attestation-manifest   (SBOM)
sha256:b4641aa48a76…  unknown/unknown    attestation-manifest   (provenance)
```

Changing any one of them changes its digest, which changes the index, which breaks the signature.

## The keys

| key | signs | transparency log | public half |
|---|---|---|---|
| `ki7mt-images` | releases: everything under `docker.io/ki7mt/` | **yes** | `keys/ki7mt-images.pub` |
| `ki7mt-images-dev` | the private development images | **never** | `keys/ki7mt-images-dev.pub` |

Both are ECDSA P-256, non-exportable, non-deletable, held in Vault transit.

**Fingerprints.** A cosign public key is bare PEM and carries no name, owner or date, so the
fingerprint is the only thing that identifies it. Check the file you have against these:

| key | SHA-256 of the DER encoding |
|---|---|
| `ki7mt-images` | `85a48c089f5e9aea2f40da4d9da300f8ec7e9f88a0fee32e7d46e94084a9ee48` |
| `ki7mt-images-dev` | `6cbd5aa10dfc3c2d5376847acf769426355c57c8bac66d86478588613d92ace9` |

```sh
openssl pkey -pubin -in keys/ki7mt-images.pub -outform DER | sha256sum
```

**Why the development key never reaches the transparency log.** The log is public, permanent and
append-only. Uploading a signature for a private image would publish that image's digest and
repository name, permanently, with no way to withdraw it. Releases are public artefacts, so the
log costs nothing and lets anyone confirm when a release was signed. Development images are not,
so they are signed with `--tlog-upload=false`. This is a rule, not a preference: one setting for
both channels would leak.

**A development signature never verifies as a release.** Separate keys, and verified as a negative
test rather than assumed — `cosign verify --key ki7mt-images.pub` refuses an image signed with
`ki7mt-images-dev`.

## Where signing happens

`make publish` signs during the release, and the order matters:

1. build and scan every architecture — a fixable HIGH or CRITICAL stops the release;
2. push to a **staging tag** and read the index digest;
3. **sign the digest**;
4. create `:<version>` and `:latest` from that already-signed digest;
5. delete the staging tag.

Signing has to follow a push, because cosign signs a digest that exists in a registry. But the
release tag does not have to exist unsigned first, and on a public repository it must not — it
would be pullable and unverifiable in the gap, and a signing failure would leave a published
release to retract. Cosign signatures are bound to the digest, not the tag, so a tag created
afterwards from the same digest is signed from the instant it exists. A failure before step 4
leaves only a staging tag to clean up.

`make verify-pull` refuses an unsigned image before it starts the stack, so we verify our own
releases on the way out rather than trusting that signing happened.

## Rotation

Transit keeps earlier key versions, so rotating does not invalidate existing signatures. A new
version means a new public key and a new fingerprint, published here and announced in a GitHub
security advisory.

## A side effect on Docker Hub

cosign stores each signature as an extra tag in the same repository, named
`sha256-<digest>.sig`. It carries no architecture, and shields.io's `docker/v` badge cannot parse a
tag list containing one — every variant returns *"invalid response data"*. The version badge
therefore reads the release tag from GitHub instead, which the publish gate requires to match the
published image anyway: `CHANNEL=prod` refuses unless the tag on origin points at HEAD.

Signatures could instead be stored as OCI referrers (`--registry-referrers-mode oci-1-1`), which
would leave the tag list clean, but registry support for referrers is uneven and it changes how
verification discovers a signature. Not worth the risk for a badge.
