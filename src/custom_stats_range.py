"""
Custom Stats Range (CSR) Add-on for Anki
"""

import anki.stats
import aqt.stats
import aqt.forms
from PyQt5 import QtWidgets
from PyQt5.QtCore import QDate
from aqt.qt import qconnect
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from .util import *
from aqt.utils import tooltip
import datetime

# Copied constants
PERIOD_MONTH = 0
PERIOD_YEAR = 1
PERIOD_LIFE = 2

# Custom period used by Custom Stats Range
CSR_PERIOD = 999

# Patch: aqt/forms/stats.py: Ui_Dialog.setupUi()
# Reason: Add a new radio button (along with "1 month", "3 month", etc.)
setupUi_OLD = aqt.forms.stats.Ui_Dialog.setupUi

def setupUi_NEW(self, Dialog):
    setupUi_OLD(self, Dialog)
    # Add CSR radio button
    self.csr_option = QtWidgets.QRadioButton(self.groupBox)
    self.csr_option.setText("Custom Range:")
    self.csr_option.setObjectName("csr_option")
    self.horizontalLayout.addWidget(self.csr_option)

    today = QDate.currentDate()
    # Add Start Date input field
    self.csr_start = QtWidgets.QDateEdit(
        parent=self.groupBox,
        date=today.addDays(-30)
    )
    self.horizontalLayout.addWidget(self.csr_start)

    # Add End Date input field
    self.csr_end = QtWidgets.QDateEdit(
        parent=self.groupBox,
        date=today
    )
    self.horizontalLayout.addWidget(self.csr_end)

# Patch: anki/stats.py: CollectionStats.footer()
# Reason: Need to modify the hardcoded array used to write the footer of the Stats page
def footer_NEW(self):
    b = "<br><br><font size=1>"
    b += "Generated on %s" % time.asctime(time.localtime(time.time()))
    b += "<br>"
    if self.wholeCollection:
        deck = "whole collection"
    else:
        deck = self.col.decks.current()["name"]
    b += "Scope: %s" % deck
    b += "<br>"
    # b += "Period: %s" % ["1 month", "1 year", "deck life"][self.type]
    # TODO: Inject the actual custom range here
    if csr_enabled(self):
        b += "Period: Custom Range"
    else:
        b += "Period: %s" % ["1 month", "1 year", "deck life"][self.type]
    return b

# Patch: anki/stats.py: CollectionStats.report()
# Reason: Handle our custom CSR_PERIOD, don't let it get stored in self.type
report_OLD = anki.stats.CollectionStats.report

def report_NEW(self, type: int = PERIOD_MONTH, custom_range: tuple = (0, 30)):
    if type == CSR_PERIOD:
        # Don't store custom period in self.type, to help remain compatible with other addons
        # Enable a separate flag
        self.type_csr = True
        self.csr_start = custom_range[0]
        self.csr_end = custom_range[1]
        type = 0
    else:
        self.type_csr = False

    return report_OLD(self, type)

# Patch: aqt/stats.py: DeckStats.__init__()
# Reason: Hook the "Custom Range" radio button to the changePeriod action
deckStats_init_OLD = aqt.stats.DeckStats.__init__

def deckStats_init_NEW(self, mw):
    deckStats_init_OLD(self, mw)
    f = self.form

    # Pass CSR_PERIOD as an indicator -- it won't actually get stored in CollectionStats.type
    qconnect(f.csr_option.clicked, lambda: self.changePeriod(CSR_PERIOD))

# Patch: aqt/stats.py: DeckStats.refresh()
# Reason: Implement an alternate version that verifies & passes on 
# the custom Start & End dates to the CollectionStats object.
refresh_OLD = aqt.stats.DeckStats.refresh

def refresh_NEW(self):
    if self.period == CSR_PERIOD:
        # Verify inputted dates
        start_date = self.form.csr_start.date() # Returns QDate object
        end_date = self.form.csr_end.date()
        start_julian = start_date.toJulianDay()
        end_julian = end_date.toJulianDay()
        if start_julian > end_julian:
            tooltip("Error: Start date must not exceed end date", 5000)
        else:
            today = QDate.currentDate()
            # Anki interprets "start" as the later date, so switch them
            csr_start = end_date.daysTo(today)
            # Anki excludes the "end" date; it takes (end, start].
            # Since this is "days ago", add 1 to get the previous date
            csr_end = start_date.daysTo(today) + 1

            # --- COPY DeckStats.refresh() (with 1 change) ---
            self.mw.progress.start(parent=self)
            stats = self.mw.col.stats()
            stats.wholeCollection = self.wholeCollection
            # CSR line: modified to pass on start/end dates to CollectionStats.report()
            self.report = stats.report(
                type=self.period,
                custom_range=(csr_start, csr_end)
            )
            self.form.web.title = "deck stats"
            self.form.web.stdHtml(
                "<html><body>" + self.report + "</body></html>",
                js=["js/vendor/jquery.js", "js/vendor/plot.js"],
                context=self,
            )
            self.mw.progress.finish()
            # --- END COPY of DeckStats.refresh() ---
    else:
        refresh_OLD(self)

# Patch: anki/stats.py: CollectionStats.get_start_end_chunk()
# Reason: Add handling for the Custom stats range when calculating start & end values
def get_start_end_chunk_NEW(self, by: str = "review"):
    start = 0

    ### Custom Stats Range code begins here ###

    if csr_enabled(self):
        # Extract start & end dates that should have been stored as attributes
        start = self.csr_start
        end = self.csr_end
        # TODO: Increase chunk size according to the range
        chunk = 1
    elif self.type == PERIOD_MONTH:
    ### Custom Stats Range code ends here ###

        end, chunk = 31, 1
    elif self.type == PERIOD_YEAR:
        end, chunk = 52, 7
    else:  #  self.type == 2:
        end = None
        if self._deckAge(by) <= 100:
            chunk = 1
        elif self._deckAge(by) <= 700:
            chunk = 7
        else:
            chunk = 31
    return start, end, chunk

# Rewrite (not patch): anki/stats.py: CollectionStats._done()
# Reason: Support date ranges instead of only "last X days"
REVLOG_LRN = 0
REVLOG_REV = 1
REVLOG_RELRN = 2
REVLOG_CRAM = 3

def _done_NEW(self, end, chunk: int = 1, start = 0):
    lims = []
    if end is not None:
        lims.append(
            "id > %d" % ((self.col.sched.dayCutoff - (end * chunk * 86400)) * 1000)
        )
        # CSR line
        lims.append(
            "id < %d" % ((self.col.sched.dayCutoff - (start * chunk * 86400)) * 1000)
        )
    lim = self._revlogLimit()
    if lim:
        lims.append(lim)
    if lims:
        lim = "where " + " and ".join(lims)
    else:
        lim = ""
    # CSR line
    if self.type == PERIOD_MONTH or csr_enabled(self):
        tf = 60.0  # minutes
    else:
        tf = 3600.0  # hours
    return self.col.db.all(
        f"""
select
(cast((id/1000.0 - ?) / 86400.0 as int))/? as day,
sum(case when type = {REVLOG_LRN} then 1 else 0 end), -- lrn count
sum(case when type = {REVLOG_REV} and lastIvl < 21 then 1 else 0 end), -- yng count
sum(case when type = {REVLOG_REV} and lastIvl >= 21 then 1 else 0 end), -- mtr count
sum(case when type = {REVLOG_RELRN} then 1 else 0 end), -- lapse count
sum(case when type = {REVLOG_CRAM} then 1 else 0 end), -- cram count
sum(case when type = {REVLOG_LRN} then time/1000.0 else 0 end)/?, -- lrn time
-- yng + mtr time
sum(case when type = {REVLOG_REV} and lastIvl < 21 then time/1000.0 else 0 end)/?,
sum(case when type = {REVLOG_REV} and lastIvl >= 21 then time/1000.0 else 0 end)/?,
sum(case when type = {REVLOG_RELRN} then time/1000.0 else 0 end)/?, -- lapse time
sum(case when type = {REVLOG_CRAM} then time/1000.0 else 0 end)/? -- cram time
from revlog %s
group by day order by day"""
        % lim,
        self.col.sched.dayCutoff,
        chunk,
        tf,
        tf,
        tf,
        tf,
        tf,
    )

# Rewrite: anki/stats.py: CollectionStats._periodDays()
# Reason: Support date ranges instead of only computing "# of days ago"
def _periodDays_NEW(self):
    start, end, chunk = self.get_start_end_chunk()
    if end is None:
        return (start * chunk, None)
    return (start * chunk, end * chunk)

# Patch: anki/stats.py: CollectionStats._daysStudied()
# Reason: Support date ranges instead of just "last X days" (same as _done())
def _daysStudied_NEW(self):
    lims = []
    start, end = _periodDays_NEW(self)
    if end:
        lims.append("id > %d" % ((self.col.sched.dayCutoff - (end * 86400)) * 1000))
        lims.append("id < %d" % ((self.col.sched.dayCutoff - (start * 86400)) * 1000))
    rlim = self._revlogLimit()
    if rlim:
        lims.append(rlim)
    if lims:
        lim = "where " + " and ".join(lims)
    else:
        lim = ""
    ret = self.col.db.first(
        """
select count(), abs(min(day)) from (select
(cast((id/1000 - ?) / 86400.0 as int)+1) as day
from revlog %s
group by day order by day)"""
        % lim,
        self.col.sched.dayCutoff,
    )
    assert ret
    return ret

# Patch: anki/stats.py: CollectionStats._eases()
# Reason: Fix the selection of data used to create the "Answer Buttons" (Ease) plot
# Similar to _done()
def _eases_NEW(self) -> Any:
    lims = []
    lim = self._revlogLimit()
    if lim:
        lims.append(lim)
    (start, end) = _periodDays_NEW(self)
    if end is not None:
        lims.append(
            "id > %d" % ((self.col.sched.dayCutoff - (end * 86400)) * 1000)
        )
        # CSR line
        lims.append(
            "id < %d" % ((self.col.sched.dayCutoff - (start * 86400)) * 1000)
        )
    if lims:
        lim = "where " + " and ".join(lims)
    else:
        lim = ""
    # (Update deprecated method)
    # if self.col.schedVer() == 1:
    if self.col.sched_ver() == 1:
        ease4repl = "3"
    else:
        ease4repl = "ease"
    return self.col.db.all(
        f"""
select (case
when type in ({REVLOG_LRN},{REVLOG_RELRN}) then 0
when lastIvl < 21 then 1
else 2 end) as thetype,
(case when type in ({REVLOG_LRN},{REVLOG_RELRN}) and ease = 4 then %s else ease end), count() from revlog %s
group by thetype, ease
order by thetype, ease"""
        % (ease4repl, lim)
    )

# Patch: anki/stats.py: CollectionStats.dueGraph()
# Reason: Disable the "Forecast" plot if custom stats range is enabled.
dueGraph_OLD = anki.stats.CollectionStats.dueGraph

def dueGraph_NEW(self):
    if csr_enabled(self):
        txt = self._title("Forecast", "(Graph omitted by Custom Stats Range.)")
        return txt
    else:
        return dueGraph_OLD(self)

# Patch: anki/stats.py: CollectionStats.ivlGraph()
# Reason: Disable the "Intervals" plot if custom stats range is enabled.
ivlGraph_OLD = anki.stats.CollectionStats.ivlGraph

def ivlGraph_NEW(self):
    if csr_enabled(self):
        txt = self._title("Intervals", "(Graph omitted by Custom Stats Range.)")
        return txt
    else:
        return ivlGraph_OLD(self)

# Patch: anki/stats.py: CollectionStats._ansInfo()
# Reason: Add support for date ranges, instead of "last X days"
# (This function handles the text below the "Review Count" and "Review Time" plots.)
def _ansInfo_NEW(
    self,
    totd: List[Tuple[int, float]],
    studied: int,
    first: int,
    unit: str,
    convHours: bool = False,
    total: Optional[int] = None,
) -> Tuple[str, int]:
    assert totd
    tot = totd[-1][1]
    # CSR line
    period_start, period_end = _periodDays_NEW(self)
    if not period_end:
        # base off earliest repetition date
        period_end = self._deckAge("review")

    # CSR line
    period = period_end - period_start

    i: List[str] = []
    self._line(
        i,
        "Days studied",
        "<b>%(pct)d%%</b> (%(x)s of %(y)s)"
        % dict(x=studied, y=period, pct=studied / float(period) * 100),
        bold=False,
    )
    if convHours:
        tunit = "hours"
    else:
        tunit = unit
    # T: unit: can be hours, minutes, reviews... tot: the number of unit.
    self._line(i, "Total", "%(tot)s %(unit)s" % dict(unit=tunit, tot=int(tot)))
    if convHours:
        # convert to minutes
        tot *= 60
    self._line(i, "Average for days studied", self._avgDay(tot, studied, unit))
    if studied != period:
        # don't display if you did study every day
        self._line(i, "If you studied every day", self._avgDay(tot, period, unit))
    if total and tot:
        perMin = total / float(tot)
        average_secs = (tot * 60) / total
        self._line(
            i,
            "Average answer time",
            # self.col.tr(
            #     TR.STATISTICS_AVERAGE_ANSWER_TIME,
            #     **{"cards-per-minute": perMin, "average-seconds": average_secs},
            # ),

            # (Update deprecated method)
            self.col.tr.statistics_average_answer_time(perMin, average_secs),
        )
    return self._lineTbl(i), int(tot)


# Patch: anki/stats.py: CollectionStats.repsGraphs()
# Reason: Add support for date ranges, instead of "last X days"
# (This function builds the "Review Count" and "Review Time" plots.)
colYoung = "#7c7"
colMature = "#070"
colCum = "rgba(0,0,0,0.9)"
colLearn = "#00F"
colRelearn = "#c00"
colCram = "#ff0"
colIvl = "#077"
colHour = "#ccc"
colTime = "#770"
colUnseen = "#000"
colSusp = "#ff0"
def repsGraphs_NEW(self):
        # start, days, chunk = self.get_start_end_chunk()
        start, end, chunk = self.get_start_end_chunk()

        data = _done_NEW(self, end, chunk, start)
        if not data:
            return ""
        conf = dict(
            xaxis=dict(tickDecimals=0, max=0.5),
            yaxes=[dict(min=0), dict(position="right", min=0)],
        )
        if end is not None:
            # pylint: disable=invalid-unary-operand-type
            conf["xaxis"]["min"] = -end + 0.5

        # CSR line
        conf["xaxis"]["max"] = -start + 0.5

        def plot(id, data, ylabel, ylabel2):
            return self._graph(
                id, data=data, conf=conf, xunit=chunk, ylabel=ylabel, ylabel2=ylabel2
            )

        # reps
        (repdata, repsum) = self._splitRepData(
            data,
            (
                (3, colMature, "Mature"),
                (2, colYoung, "Young"),
                (4, colRelearn, "Relearn"),
                (1, colLearn, "Learn"),
                (5, colCram, "Cram"),
            ),
        )
        txt1 = self._title("Review Count", "The number of questions you have answered.")
        txt1 += plot("reps", repdata, ylabel="Answers", ylabel2="Cumulative Answers")
        (daysStud, fstDay) = self._daysStudied()
        rep, tot = _ansInfo_NEW(self, repsum, daysStud, fstDay, "reviews")
        txt1 += rep
        # time
        (timdata, timsum) = self._splitRepData(
            data,
            (
                (8, colMature, "Mature"),
                (7, colYoung, "Young"),
                (9, colRelearn, "Relearn"),
                (6, colLearn, "Learn"),
                (10, colCram, "Cram"),
            ),
        )
        # CSR line
        if self.type == PERIOD_MONTH or csr_enabled(self):
            t = "Minutes"
            convHours = False
        else:
            t = "Hours"
            convHours = True
        txt2 = self._title("Review Time", "The time taken to answer the questions.")
        txt2 += plot("time", timdata, ylabel=t, ylabel2="Cumulative %s" % t)
        rep, tot2 = _ansInfo_NEW(
            self, timsum, daysStud, fstDay, "minutes", convHours, total=tot
        )
        txt2 += rep
        return self._section(txt1) + self._section(txt2)

# Patch: anki/stats.py: CollectionStats._hourRet()
# Reason: Support custom stats range in computation of data for "Hourly Breakdown" plot.
def _hourRet_NEW(self):
    lim = self._revlogLimit()
    if lim:
        lim = " and " + lim
    if self.col.schedVer() == 1:
        sd = datetime.datetime.fromtimestamp(self.col.crt)
        rolloverHour = sd.hour
    else:
        rolloverHour = self.col.conf.get("rollover", 4)
    # pd = self._periodDays()
    start, end = _periodDays_NEW(self)
    if end:
        lim += " and id > %d" % ((self.col.sched.dayCutoff - (86400 * end)) * 1000)
        # CSR line
        lim += " and id < %d" % ((self.col.sched.dayCutoff - (86400 * start)) * 1000)
    return self.col.db.all(
        f"""
select
23 - ((cast((? - id/1000) / 3600.0 as int)) %% 24) as hour,
sum(case when ease = 1 then 0 else 1 end) /
cast(count() as float) * 100,
count()
from revlog where type in ({REVLOG_LRN},{REVLOG_REV},{REVLOG_RELRN}) %s
group by hour having count() > 30 order by hour"""
        % lim,
        self.col.sched.dayCutoff - (rolloverHour * 3600),
    )

# Apply monkey patches

aqt.forms.stats.Ui_Dialog.setupUi = setupUi_NEW

anki.stats.CollectionStats.footer = footer_NEW

anki.stats.CollectionStats.report = report_NEW

aqt.stats.DeckStats.__init__ = deckStats_init_NEW

aqt.stats.DeckStats.refresh = refresh_NEW

anki.stats.CollectionStats.get_start_end_chunk = get_start_end_chunk_NEW

anki.stats.CollectionStats.dueGraph = dueGraph_NEW

anki.stats.CollectionStats.ivlGraph = ivlGraph_NEW

anki.stats.CollectionStats._daysStudied = _daysStudied_NEW

anki.stats.CollectionStats._eases = _eases_NEW

anki.stats.CollectionStats.repsGraphs = repsGraphs_NEW

anki.stats.CollectionStats._hourRet = _hourRet_NEW
