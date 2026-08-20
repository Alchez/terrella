"""Terrella's data pipeline: what turns published elevation data into the rasters the site serves.

HOW THIS PACKAGE IS LAID OUT, because a directory listing cannot say it and every reader asks.
There are two kinds of thing here, and which one a new module is decides where it belongs.

  * A SUB-PACKAGE holds stages that run. Most are named for the step they perform and sit roughly in
    the order the data moves: `acquire` fetches published data, `fuse` welds land and sea into one
    heightfield, `frame` resolves a country into render parameters, `tile` cuts the raster pyramids,
    `compose` assembles the delivered vectors and image variants. `render` is the hero rig, one
    country into one Cycles image. Two are named for what they hold instead of for a step: `look` is
    the surface and the light, below, and `profile` is instrumentation.

  * A MODULE AT THIS LEVEL is a law or a seam that more than one stage reads, and it is here BECAUSE
    the copies drifted. `mercator` exists because two shading modules each carried their own Earth
    radius and their own inverse projection; `raster_io` because the same windowed-read fix landed at
    one call site and was missed at its siblings four separate times. So a new root module is a claim
    that a second reader exists, and the test is: change one copy, what goes red? Nothing red means
    it does not belong here yet.

`look` AND `render` ARE THE PAIR MOST EASILY CONFUSED, so it is worth stating once here rather than
being rediscovered from the import graph. `look` is what a surface is painted with and how it is lit,
read by BOTH rigs. `render` is the hero rig alone. The dependency runs one way, `render` onto `look`,
and a cycle between them means a module sits on the wrong side.
"""
