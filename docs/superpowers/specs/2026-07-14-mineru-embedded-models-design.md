# MinerU Embedded Models Design

## Goal

Prevent an empty host directory from hiding the MinerU configuration and model
cache baked into `mineru:latest`. The deployed MinerU services will always use
the models stored in the image.

## Chosen Approach

Remove the `./mineru-home:/root` bind mount from both `mineru-router` and
`mineru-gradio`. Keep `MINERU_MODEL_SOURCE=local`; inside the container this
selects the image's `/root/mineru.json`, pipeline model, and VLM model without
attempting network access.

External `/root` model directories will no longer be supported by this stack.
This avoids two competing model ownership modes and removes the failure case in
which a newly created `mineru-home` directory masks all image content under
`/root`.

## Configuration And Script Changes

- Remove the `/root` bind mount from the source MinerU Compose file and from the
  existing unpacked air-gap package.
- Stop creating `ragflow/docker/mineru-home` during packaging and deployment.
- Remove the `-IncludeMineruHome` and `-MineruHomePath` packaging options and
  the code that copies an external MinerU home directory.
- Stop packaging the external-model download helper and remove that helper from
  the maintained deployment source.
- Update deployment documentation so it states that both pipeline and VLM
  models are embedded in `mineru:latest` and that rebuilding the image is the
  supported way to update them.
- Keep `mineru-output` and `mineru-input` mounts unchanged.

The checked-in source is authoritative. The existing ignored `dist` directory
will also be updated in place so the already-generated package can be copied to
the Linux server without rebuilding the 29 GB image archive.

## Deployment Behavior

Existing Linux installations must replace their MinerU Compose file and
recreate `mineru-router` (and `mineru-gradio` when enabled). A container restart
is insufficient because Docker mount configuration only changes when the
container is recreated.

The old host `mineru-home` directory is not deleted automatically. It becomes
unused and may be removed manually after successful verification. This avoids
destructive migration behavior.

## Validation

Automated regression checks will verify that:

1. No maintained or packaged Compose file mounts a path at `/root`.
2. Deployment and packaging scripts do not create, copy, or package
   `mineru-home`.
3. Packaging no longer exposes the removed external-model parameters or helper.
4. Source and packaged documentation no longer instruct operators to prepare
   an external MinerU home.
5. Rendered Compose configuration still retains `/tmp/mineru` and `/data/input`
   mounts and sets `MINERU_MODEL_SOURCE=local`.

Runtime verification will inspect a fresh `mineru:latest` container without a
`/root` mount and confirm that `models-dir.pipeline` and `models-dir.vlm` both
resolve to existing directories.

## Compatibility

This is intentionally a breaking removal of the optional external-model mode.
It is compatible with the current air-gap image because that image contains
`/root/mineru.json` and both required model sets. Users who need different model
versions must rebuild and redistribute `mineru:latest`.
