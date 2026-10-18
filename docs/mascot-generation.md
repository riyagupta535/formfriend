# Form Friend mascot

Generated with the built-in image generation tool, using the user's attached
mascot as a character reference. The transparent asset is used by the shared
`frontend/app/components/mascot.tsx` component on all four pages.

Original asset: `frontend/public/images/formfriend-mascot.png`

## Final prompt

Use case: stylized-concept. Asset type: transparent PNG mascot cutout for the Form Friend web application. Input image 1 is the user's character reference. Create a faithful polished soft 3D rendition of this same character: very round squat pear-shaped turquoise teal creature, small feet, cream rounded belly patch with a small teal folded-corner triangle at lower right, two flexible teal antenna stems each topped by a rounded cream paper sheet with a teal folded upper right corner, large glossy deep navy oval eyes with white highlights and cream eye edges, tiny curved navy smile, small curved eyebrows, peach blush cheeks. Two short chubby arms curve inward, gently cupping a luminous warm golden orb just above the belly. Match the reference proportions, sweet expression, tilted head, lighting, soft finely textured rubber/plush material, dimensional shading and cream/teal colors very closely. Full body including both antennae and feet, front-facing slight three-quarter angle matching reference, centered, narrow clean transparent margin. High quality rounded cinematic 3D character render, soft studio light from upper left, gentle golden glow lighting hands. Actual alpha transparency, no background, no black rectangle, no text, no logos, no watermark, no other objects. This should look like the reference image rather than a flat vector illustration.

## Antenna removal edit

Tool: built-in image generation, editing the existing PNG with transparency.
The original asset is retained. This edit produced
`frontend/public/images/formfriend-mascot-no-antennae.png`; the latest app version
is listed in the necktie edit below.

Final edit prompt:

Use case: precise-object-edit. Input image is the edit target: the existing Form Friend mascot PNG. Remove BOTH antennae completely: erase the two curved teal stems AND the two cream paper-shaped tips with folded teal corners. Replace those removed pixels with actual alpha transparency. Smooth only the two small attachment spots at the crown to create a naturally uninterrupted rounded teal head contour. Keep everything else unchanged: the same exact face and mouth location, glossy eyes, eyebrows, blush cheeks, turquoise body, hands, glowing golden orb, cream belly, teal belly triangle, feet, material texture, shading, lighting, and slight tilt. Preserve the original canvas aspect ratio, framing, body size and placement: do not crop, zoom, enlarge, recenter or move the character up into the space left by the removed antennae. This asset has an animated mouth overlay in the app, so the face must remain at exactly the same relative position in the canvas. Retain the full transparent area above the head where the antennae used to be. No ears, no new head appendages, no text, no other changes. Output a transparent PNG cutout.

## Necktie edit

Tool: built-in image generation, editing the antenna-free PNG with transparency.
App asset: `frontend/public/images/formfriend-mascot-tie.png`.
Previous versions are retained.

Final edit prompt:

Use case: precise-object-edit. Edit target: attached antenna-free teal Form Friend mascot. Remove the golden orb completely and remove all its warm light spill and halo from the chest, hands and belly, restoring natural soft teal and cream shading. Add a small tasteful deep navy necktie with a simple knot directly below the smile, hanging down the center of its chest onto the cream belly. It should be a normal long necktie with a pointed bottom, not a bow tie. Keep the tie proportionate and cute with softly textured fabric, dimensional shading, and no writing or logo. The two chubby hands can remain lifted beside the tie as though gently adjusting it; make only small hand changes if necessary to avoid holding an invisible orb. Preserve the exact mascot identity, round antenna-free silhouette, eyes, smile, eyebrows, cheeks, cream belly and teal triangle, tiny feet, soft plush/rubber material, colors, lighting and tilt. CRITICAL: retain original canvas aspect ratio, transparent margins, full-body framing, scale, and placement. Do not crop, zoom, enlarge, recenter or move the face: an app mouth overlay depends on its exact relative position. Keep the empty transparent space above the head. True transparent alpha background, no scene, no new antennae, no other accessories, no text. Only remove orb and its glow and add the navy necktie.


## Hat edit

The app now uses `frontend/public/images/formfriend-mascot-hat.png`.
The tie was removed and replaced with a navy bowler hat with a teal band.
Generated with built-in image editing; see [the final hat edit prompt](mascot-hat-prompt.md).


## Top hat refinement

Current app asset: `frontend/public/images/formfriend-mascot-top-hat.png`.
The bowler hat was replaced with a tall navy top hat and teal band using built-in
image editing. See [the final edit prompt](mascot-hat-prompt.md).
