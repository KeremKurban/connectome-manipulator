"""Null manipulator - does not do anything"""

from connectome_manipulator import log
from connectome_manipulator.connectome_manipulation.manipulation import Manipulation


class NullManipulation(Manipulation):
    """This is just a dummy manipulation performing no manipulation at all.

    This function is intended as a control condition to run the manipulation pipeline
    without actually manipulating the connectome.
    """

    def apply(self, edges_table, split_ids, aux_config, **kwargs):
        """No manipulation (control condition)."""
        log.info("Nothing to do")

        return edges_table
