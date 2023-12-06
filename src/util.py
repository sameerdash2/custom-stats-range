from anki.stats import CollectionStats
from anki.scheduler.base import SchedulerBase
from anki.utils import pointVersion

# For Anki 2.1.x releases, it will return the x.
# For Anki 23.10+, it packs the full version into 6 digits.
anki_point_ver = pointVersion()


def csr_enabled(self: CollectionStats):
    return (
        hasattr(self, "type_csr")
        and self.type_csr == True
        and hasattr(self, "csr_start")
        and hasattr(self, "csr_end")
    )


def get_day_cutoff(self: SchedulerBase):
    if (anki_point_ver >= 50):
        return self.day_cutoff
    else:
        return self.dayCutoff
