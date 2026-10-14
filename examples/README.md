# Workflow examples

These are schema examples, not ready-to-run show configurations. Replace `C:/USER_DELIVERY_ROOT`,
plate paths, Group source paths and **every colorspace/color-setting label** with user-provided values
observed in your host. Create destination directories first. `.nknc` targets require NC; commercial
hosts use `.nk`. No particular OCIO/ACES configuration is inferred by these files.

Shot manifests declare the root containing all script and Write destinations. CSV mapping keys are
literal headers and values are dot-separated shot fields. Start with explicit `shot_defaults` containing
the required nested objects and plate slots, then map columns into them. CSV is conversion only;
the validated JSON manifest is authoritative. Error results must be resolved before planning.

Layer order is meaningful: the first layer is the base, then each new layer is Merge input A (1),
and the accumulated result is input B (0). A mask is input 2 with its exact channel. Saving and
rendering a layered Group are separate operations.
