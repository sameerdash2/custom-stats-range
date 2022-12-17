from anki.stats import CollectionStats
from anki.sched import Scheduler
from anki import version

anki_patch_ver = int(version.split(".")[2])


def csr_enabled(self: CollectionStats):
    return (
        hasattr(self, "type_csr")
        and self.type_csr == True
        and hasattr(self, "csr_start")
        and hasattr(self, "csr_end")
    )


def get_day_cutoff(self: Scheduler):
    if (anki_patch_ver >= 50):
        return self.day_cutoff
    else:
        return self.dayCutoff
