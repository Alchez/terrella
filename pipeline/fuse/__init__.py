"""Weld separately published surfaces into the one heightfield every renderer reads.

Land elevation and bathymetry become a single seamless grid here, and nothing downstream re-fuses.
ONLY those two are fused: every other surface layer is warped onto the render grid at composite time
and never enters this master, which is also why a finer re-fuse would not have to redo any of them.
"""
