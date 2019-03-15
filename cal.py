#!/usr/bin/env python3

import argparse
import datetime
import hashlib
import sys
import uuid

import bs4
import icalendar
import pytz
import requests

LOCALTZ = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

SEQ_NUM = 1
TZID = 'Australia/Sydney'
CALS = {
        67: 'Music',
        69: 'Parent',
        66: 'Whole School',
        63: 'Yr 10',
        64: 'Yr 11',
        65: 'Yr 12',
        60: 'Yr 7',
        61: 'Yr 8',
        62: 'Yr 9'
        }
URL_FMT = "http://web1.jamesruse-h.schools.nsw.edu.au/webcal/calendar/{}?type=term&value={}&year={}"

def cal_names_to_ids(names):
    """
    Convert names of calendars to their equivalent id
    """
    def cal2id(name):
        """
        Convert a single name
        """
        for key, value in CALS.items():
            if value.casefold() == name.casefold():
                return key
        return None

    return set(map(cal2id, names))

def process_event(dom, _cal):
    """
    Extract useful details from a DOM element into a dict
    """
    strings = list(dom.strings)
    if len(strings) > 1: # has time
        return dict(time=strings[0], event=strings[1])
    return dict(event=strings[0])

def parse_duration(duration):
    """
    Parse a duration string into individual datetimes
    """
    bits = duration.split(' - ')
    out = []
    formats = ['%I:%M%p', '%I%p']
    for bit in bits:
        timestamp = None
        for fmt in formats:
            try:
                timestamp = datetime.datetime.strptime(bit, fmt)
            except ValueError:
                pass
            else:
                break
        if timestamp is None:
            raise ValueError(f"Unkown timestamp '{bit}'")
        out.append(timestamp)
    return out

def as_ical_event(year, event):
    """
    Convert an event dict into an ical event
    """
    md5 = hashlib.md5()
    md5.update(event['event'].encode('utf-8'))
    md5.update(event['day'].encode('utf-8'))
    md5.update(str(year).encode('utf-8'))
    if 'time' in event:
        md5.update(event['time'].encode('utf-8'))

    guid = uuid.UUID(bytes=md5.digest())

    ics_event = icalendar.Event()
    ics_event.add('summary', event['event'])
    ics_event.add('uid', str(guid) + '@ralismark.github.io')
    ics_event.add('sequence', str(SEQ_NUM))

    date = datetime.datetime.strptime(event['day'], '%b %d').replace(year=year, tzinfo=LOCALTZ)
    if 'time' in event: # specific time
        dtstart, dtend = parse_duration(event['time'])
        duration = dtend - dtstart
        when = datetime.datetime.combine(date, dtstart.time(), pytz.timezone(TZID))
        ics_event.add('dtstart', when)
        ics_event.add('duration', duration)
    else: # all day
        ics_event.add('dtstart', date)
        ics_event.add('dtend', date)

    return ics_event

def get_events(term, year, cals):
    """
    Get all events in a certain term and year
    """
    events = []
    for calid in cal_names_to_ids(cals):
        print("Calendar '{}' year {} term {}...".format(CALS[calid], year, term), file=sys.stderr)
        url = URL_FMT.format(calid, term, year)
        req = requests.get(url)
        # req.raise_for_status() # report errors

        dom = bs4.BeautifulSoup(req.text, 'html5lib')
        days = dom.select('table.calendar tr.calendar-row > td.print-borders')
        day_names = [x.select('.calendar-cell-date > div')[0].text.replace('\xa0', ' ')
                     for x in days]
        event_list = [[process_event(y, CALS[calid] + ': ')
                       for y in x.select('.event')] for x in days]

        for day in zip(day_names, event_list):
            for event in day[1]:
                entry = dict(day=day[0])
                entry.update(event)
                events.append(entry)
    return events

def generate_vtimezone(tzid):
    """
    Generate a vtimezone from a timezone id.
    See https://gist.github.com/pgcd/2f2e880e64044c1d86f8d50c0b6f235b.
    """
    if not tzid:  # UTC as a fallback doesn't work, since it has no transition info
        return None
    timezone = pytz.timezone(tzid)
    now = datetime.datetime.now()
    dst1, std1, dst2, std2 = filter(lambda x: x[0].year in (now.year, now.year + 1),
                                    zip(timezone._utc_transition_times, timezone._transition_info))

    vtz = icalendar.Timezone(TZID=tzid)

    tz_comp = icalendar.TimezoneDaylight()
    utcoffset, _, tzname = dst1[1]
    offsetfrom = std1[1][0]
    tz_comp.add('dtstart', dst1[0] + offsetfrom)
    tz_comp.add('rdate', dst1[0] + offsetfrom)
    tz_comp.add('rdate', dst2[0] + offsetfrom)
    tz_comp.add('tzoffsetfrom', offsetfrom)
    tz_comp.add('tzoffsetto', utcoffset)
    tz_comp.add('tzname', tzname)
    vtz.add_component(tz_comp)

    tz_comp = icalendar.TimezoneStandard()
    utcoffset, _, tzname = std1[1]
    offsetfrom = dst1[1][0]
    tz_comp.add('dtstart', std1[0] + offsetfrom)
    tz_comp.add('rdate', std1[0] + offsetfrom)
    tz_comp.add('rdate', std2[0] + offsetfrom)
    tz_comp.add('tzoffsetfrom', offsetfrom)
    tz_comp.add('tzoffsetto', utcoffset)
    tz_comp.add('tzname', tzname)
    vtz.add_component(tz_comp)

    return vtz

def make_cal(seq):
    """
    Make a calendar from a sequence of events
    """
    cal = icalendar.Calendar()
    cal.add('version', '2.0')
    cal.add('prodid', '-//Sentral Calendar Script//ralismark.github.io//')
    cal.add('x-wr-calname', 'Sentral Calendar')

    cal.add_component(generate_vtimezone(TZID))

    for event in seq:
        cal.add_component(event)
    return cal

def main():
    parser = argparse.ArgumentParser(
        description='Process and print Sentral calendar into an iCal file')
    parser.add_argument('--year', nargs=1, type=int, dest='year',
                        action='store', default=datetime.datetime.now().year)
    parser.add_argument('--term', nargs='+', type=int, dest='terms', default=[1, 2, 3, 4])
    parser.add_argument('--cals', nargs='*', type=str, dest='cals', default=[])

    # print(parser.parse_args())
    args = parser.parse_args()

    if not args.cals:
        print("\n".join(CALS.values()))
        return

    print("Getting events for {}, terms: {}...".format(
        args.year, ", ".join(map(str, args.terms))), file=sys.stderr)
    events = [i for term in args.terms for i in get_events(term, args.year, args.cals)]
    print("{} total events".format(len(events)), file=sys.stderr)

    sys.stdout.buffer.write(make_cal([as_ical_event(args.year, i) for i in events]).to_ical())

if __name__ == "__main__":
    main()
