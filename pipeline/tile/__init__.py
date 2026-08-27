"""Cut a body's surface into the pyramids the globe streams, and render the poles the pyramid cannot.

A Web Mercator pyramid has no pole, so each cap is a separate azimuthal render the client composites
over the tiles. The colour cut, the terrain-RGB elevation lane and the cap renders sit together
because they answer one question between them: what does the globe fetch for this tile?
"""
