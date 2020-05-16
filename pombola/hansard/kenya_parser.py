import os
import re
import subprocess
import datetime

from django.conf import settings
from django.db import transaction

from BeautifulSoup import BeautifulSoup, BeautifulStoneSoup, Tag

from pombola.hansard.models import Sitting, Entry, Venue


# EXCEPTIONS
class KenyaParserCouldNotParseTimeString(Exception):
    pass


class KenyaParser():
    """
    # match National Assembly start and end times
    >>> result = KenyaParser.na_reg.match("The House met at 10.15 a.m.")
    >>> result.group('action')
    'met'
    >>> result.group('time')
    '10.15 a.m.'
    >>> result = KenyaParser.na_reg.match("The House rose at 6.45 p.m.")
    >>> result.group('action')
    'rose'

    # match the Senate start and end times
    >>> result = KenyaParser.sen_reg.match("The Senate met at 10.15 a.m.")
    >>> result.group('action')
    'met'
    >>> result = KenyaParser.sen_reg.match("The House met at the Senate Chamber at 10.15 a.m.")
    >>> result.group('time')
    '10.15 a.m.'
    >>> result = KenyaParser.sen_reg.match("The House met at the Senate Chamber, Parliament Buildings, at 10.15 a.m.")
    >>> result.group('time')
    '10.15 a.m.'
    >>> result = KenyaParser.sen_reg.match("The House rose at 6.45 p.m.")
    >>> result.group('action')
    'rose'
    >>> result = KenyaParser.sen_reg.match("The Senate rose at 6.45 p.m.")
    >>> result.group('action')
    'rose'

    # it should cope with the plural form of 'Senate Chamber'
    >>> result = KenyaParser.sen_reg.match("The House met at the Senate Chambers, Parliament Buildings, at 2.30 p.m. [The Speaker (Hon. Ethuro) in the Chair]")
    >>> result.group('action')
    'met'

    # it should cope with the word 'Main' appearing before 'Parliament Buildings'
    >>> result = KenyaParser.sen_reg.match("The Senate met at the Senate Chamber, Main Parliament Buildings, at 2.30 p.m.")
    >>> result.group('action')
    'met'

    # match Joint Sitting start and end times
    >>> result = KenyaParser.joint_reg.match("Parliament rose at 6.45 p.m.")
    >>> result.groups()
    ('rose', '6.45 p.m.')
    >>> result = KenyaParser.joint_reg.match("Parliament met at Fifty eight minutes past Nine o'clock in the National Assembly Chamber")
    >>> result.groups()
    ('met', "Fifty eight minutes past Nine o'clock")
    """

    na_reg  = re.compile(r"""
        The\ House\s
        (?P<action>met|rose)\s
        (?:at\ )?
        (?P<time>\d+\.\d+\ [ap].m.)""", re.VERBOSE)

    # not ideal as this could accidentally match na_reg as well,
    # relies on na_reg always being checked first
    sen_reg = re.compile(r"""
        The\ (?:House|Senate)\s
        (?P<action>met|rose)
        (?:
            \ at\ the\ Senate\ Chambers?
            (?:,\ (?:Main\ )?Parliament\ Buildings,)?
        )?
        (?:\ at\ )?
        (?P<time>\d+\.\d+\ [ap].m.)""", re.VERBOSE)

    joint_reg = re.compile(r"""
        Parliament\s
        (?P<action>(?:met|rose))\s
        at\s
        (?P<time>
            (?:(?:[A-Za-z\- ]+\ minutes?\ (?:past|to)\ )?[A-Za-z]+\ o'clock)
            |
            (?:\d+\.\d+\ [ap].m.)
        )
        (?:\ in\ the\ National\ Assembly\ Chamber)?""", re.VERBOSE)


    @classmethod
    def convert_pdf_to_html(cls, pdf_file):
        """Given a PDF parse it and return the HTML string representing it"""

        remote_host = settings.KENYA_PARSER_PDF_TO_HTML_HOST

        if remote_host:
            output = cls.convert_pdf_to_html_remote_machine(pdf_file, remote_host)
        else:
            output = cls.convert_pdf_to_html_local_machine( pdf_file )

        # cleanup some known bad chars in the output
        output = re.sub("\xfe\xff", "", output)  # BOM
        output = re.sub("\u201a\xc4\xf4", "\xe2\x80\x99", output) # smart quote

        return output


    @classmethod
    def convert_pdf_to_html_local_machine(cls, pdf_file):
        """Use local pdftohtml binary to convert the pdf to html"""

        pdftohtml_cmd = 'pdftohtml'

        # get the version number of pdftohtml and check that it is acceptable - see
        # 'hansard/notes.txt' for issues with the output from different versions.
        # Version output is sent to stderr
        ( ignore_me, version_error ) = subprocess.Popen(
            [ pdftohtml_cmd, '-v' ],
            shell = False,
            stderr = subprocess.PIPE,
        ).communicate()
        wanted_version = 'pdftohtml version 0.48.0'
        if wanted_version not in version_error:
            raise Exception( "Bad pdftohtml version - got '%s' but want '%s'" % (version_error, wanted_version) )

        ( convert_output, ignore_me ) = subprocess.Popen(
            [ pdftohtml_cmd, '-stdout', '-noframes', '-enc', 'UTF-8', pdf_file.name ],
            shell = False,
            stdout = subprocess.PIPE,
        ).communicate()

        return convert_output


    @classmethod
    def convert_pdf_to_html_remote_machine(cls, pdf_file, remote):
        """Convert pdf on a remote machine"""

        bin_dir               = os.path.abspath( os.path.dirname( __file__ ) + '/bin' )
        remote_convert_script = os.path.join( bin_dir, 'convert_pdf_to_html_on_remote_machine.bash'  )

        remote_pdftohtml = subprocess.Popen(
            [ remote_convert_script, remote, pdf_file.name ],
            shell = False,
            stdout = subprocess.PIPE,
        )

        ( output, ignore ) = remote_pdftohtml.communicate()
        return output


    @classmethod
    def convert_html_to_data(cls, html):

        # Clean out all the &nbsp; now. pdftohtml puts them to preserve the lines
        html = re.sub( r'&nbsp;', ' ', html )
        html = re.sub( r'&#160;', ' ', html )

        # create a soup out of the html
        soup = BeautifulSoup(
            html,
            convertEntities=BeautifulStoneSoup.HTML_ENTITIES
        )

        if not soup.body:
            raise Exception, "No <body> was found - output probably isn't HTML"
        contents = soup.body.contents

        # counters to use in the loops below
        br_count    = 0
        page_number = 1

        filtered_contents = []

        while len(contents):
            line = contents.pop(0)

            # get the tag name if there is one
            tag_name = line.name if type(line) == Tag else None

            # count <br> tags - we use two or more in succession to decide that
            # we've moved on to a new bit of text
            if tag_name == 'br':
                br_count += 1
                continue

            # skip empty lines
            if tag_name == None:
                text_content = unicode(line)
            else:
                text_content = line.text

            if re.match( r'\s*$', text_content ):
                continue


            # For Assembly
            # check for something that looks like the page number - when found
            # delete it and the two lines that follow
            if tag_name == 'b':
                page_number_match = re.match( r'(\d+)\s{10,}', line.text )
                if page_number_match:
                    # up the page number - the match is the page that we are leaving
                    page_number = int(page_number_match.group(0)) + 1
                    # skip on to the next page
                    while len(contents):
                        item = contents.pop(0)
                        if type(item) == Tag and item.name == 'hr': break
                    continue

            # For Senate
            # check for something that looks like the page number
            if tag_name == 'b':
                page_number_match = re.search( r'\s{10,}(\d+)', line.text )
                if page_number_match:
                    # set the page number - the match is the page that we are on
                    page_number = int(page_number_match.group(0))
                    continue

            if tag_name == 'b':
                if re.search( r'\s*Disclaimer:', line.text ):
                    # This is a disclaimer line that we can skip
                    continue

            # if br_count > 0:
            #     print 'br_count: ' + str(br_count)
            # print type( line )
            # # if type(line) == Tag: print line.name
            # print "%s: >>>%s<<<" % (tag_name, text_content)
            # print '------------------------------------------------------'

            text_content = text_content.strip()
            text_content = re.sub( r'\s+', ' ', text_content )

            filtered_contents.append(dict(
                tag_name     = tag_name,
                text_content = text_content,
                br_count     = br_count,
                page_number  = page_number,
            ))

            br_count = 0

        # go through all the filtered_content and using the br_count determine
        # when lines should be merged
        merged_contents = []

        for line in filtered_contents:

            # print line
            br_count = line['br_count']

            # Join lines that have the same tag_name and are not too far apart
            same_tag_name_test = (
                    br_count <= 1
                and len(merged_contents)
                and line['tag_name'] == merged_contents[-1]['tag_name']
            )

            # Italic text in the current unstyled text
            inline_italic_test = (
                    br_count == 0
                and len(merged_contents)
                and line['tag_name'] == 'i'
                and merged_contents[-1]['tag_name'] == None
            )

            # Merge lines tha meet one of the above tests
            if ( same_tag_name_test or inline_italic_test ):
                new_content = ' '.join( [ merged_contents[-1]['text_content'], line['text_content'] ] )
                new_content = re.sub( r'\s+,', ',', new_content )
                merged_contents[-1]['text_content'] = new_content
            else:
                merged_contents.append( line )

        # now go through and create some meaningful chunks from what we see
        meaningful_content = []
        last_speaker_name  = ''
        last_speaker_title = ''

        while len(merged_contents):

            line = merged_contents.pop(0)
            next_line = merged_contents[0] if len(merged_contents) else None

            # print '----------------------------------------'
            # print line

            # if the content is italic then it is a scene
            if line['tag_name'] == 'i':
                meaningful_content.append({
                    'type': 'scene',
                    'text': line['text_content'],
                    'page_number': line['page_number'],
                })
                continue

            # if the content is all caps then it is a heading
            if line['text_content'] == line['text_content'].upper():
                meaningful_content.append({
                    'type': 'heading',
                    'text': line['text_content'],
                    'page_number': line['page_number'],
                })
                last_speaker_name  = ''
                last_speaker_title = ''
                continue

            # It is a speech if we have a speaker and it is not formatted
            if line['tag_name'] == None and last_speaker_name:

                # do some quick smarts to see if we can extract a name from the
                # start of the speech.
                speech = line['text_content']

                matches = re.match( r'\(([^\)]+)\):(.*)', speech )
                if matches:
                    last_speaker_title = last_speaker_name
                    last_speaker_name = matches.group(1)
                    speech = matches.group(2)
                else:
                    # strip leading colons that may have been missed when the
                    # name was extracted (usually the colon was outside the
                    # bold tags around the name)
                    speech = re.sub( r'^:\s*', '', speech)

                meaningful_content.append({
                    'speaker_name':  last_speaker_name,
                    'speaker_title': last_speaker_title,
                    'text': speech,
                    'type': 'speech',
                    'page_number': line['page_number'],
                })

                # print meaningful_content[-1]

                continue

            # If it is a bold line and the next line is 'None' and is no
            # br_count away then we have the start of a speech.
            if (
                    line['tag_name']      == 'b'
                and next_line
                and next_line['tag_name'] == None
                and next_line['br_count'] == 0
            ):
                last_speaker_name = line['text_content'].strip(':')
                last_speaker_title = ''
                continue

            meaningful_content.append({
                'type': 'other',
                'text': line['text_content'],
                'page_number': line['page_number'],
            })
            last_speaker_name  = ''
            last_speaker_title = ''

        hansard_data = {
            'meta': cls.extract_meta_from_transcript( meaningful_content ),
            'transcript': meaningful_content,
        }

        return hansard_data


    @classmethod
    def extract_meta_from_transcript(cls, transcript):

        # create the two venues
        national_assembly, created = Venue.objects.get_or_create(
            slug = 'national_assembly',
            defaults = {"name": "National Assembly"},
        )
        senate, created = Venue.objects.get_or_create(
            slug = 'senate',
            defaults = {"name": "Senate"},
        )

        reg   = None
        venue = None

        # work out which one we should use
        for line in transcript:
            text = line.get('text', '')
            if cls.na_reg.search(text):
                reg = KenyaParser.na_reg
                venue = national_assembly
                break
            elif cls.sen_reg.search(text):
                reg = KenyaParser.sen_reg
                venue = senate
                break
            elif cls.joint_reg.search(text):
                reg = KenyaParser.joint_reg
                venue = national_assembly
                break

        if venue is None:
            raise Exception, "Failed to find the Venue"

        results = {
            'venue': venue.slug,
        }

        for line in transcript:
            text = line.get('text', '')

            match = reg.match(text)
            if not match: continue

            groups = match.groupdict()

            hhmm = cls.parse_time_string( groups['time'] )

            if groups['action'] == 'met':
                results['start_time'] = hhmm
            else:
                results['end_time'] = hhmm

        return results


    @classmethod
    def parse_time_string(cls, time_string):
        """Given a string input return HH:MM:SS format string, or raises SourceCouldNotParseTimeString if it can't be done"""

        # A quick google did not reveal a generic time parsing library, although
        # there must be one.

        time_regex = re.compile( r'(\d+)\.(\d+) (a|p)')
        match_simple = time_regex.match(time_string)

        verbose_time_regex = re.compile(r"(?:(?:(?P<minutes>[A-Za-z\- ]+) minutes? (?P<qualifier>past|to) ))?(?P<hour>[tA-Za-z]+) o'clock")
        match_verbose = verbose_time_regex.match(time_string)

        if match_simple:
            hour, minute, am_or_pm = match_simple.groups()

            hour   = int(hour)
            minute = int(minute)

            if am_or_pm == 'p' and hour < 12:
                hour += 12

        elif match_verbose:
            # attempt to translate words to numbers
            hour   = cls.number_word_to_int(match_verbose.group('hour'))
            minute = cls.number_word_to_int(match_verbose.group('minutes'))

            # I don't think this phrasing is used, but just in case
            if match_verbose.group('qualifier') == 'to':
                minute = 60 - minute
                hour = hour - 1

            # make horrible assumption to get am/pm
            if hour < 8:
                hour += 12
        else:
            raise KenyaParserCouldNotParseTimeString( "bad time string: '%s'" % time_string )

        return '%02u:%02u:00' % (hour,minute)


    @classmethod
    # adapted from http://stackoverflow.com/questions/493174/is-there-a-way-to-convert-number-words-to-integers-python#answer-493788
    def number_word_to_int(cls, textnum):
        if not textnum:
            return 0

        numwords = {}
        units = [
            "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
            "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
            "sixteen", "seventeen", "eighteen", "nineteen",
        ]

        tens = ["", "", "twenty", "thirty", "forty", "fifty"]

        for idx, word in enumerate(units):  numwords[word] = (1, idx)
        for idx, word in enumerate(tens):   numwords[word] = (1, idx * 10)

        textnum = textnum.replace('-', ' ').lower().strip()
        current = 0
        for word in textnum.split():
            if word not in numwords:
              raise Exception("Illegal word: " + word)

            scale, increment = numwords[word]
            current = current * scale + increment

        return current


    @classmethod
    def create_entries_from_data_and_source( cls, data, source ):
        """Create the needed sitting and entries"""

        venue = Venue.objects.get( slug=data['meta']['venue'] )

        # Joint Sittings can be published by both Houses (identical documents)
        # prevent the same Sitting being created twice
        if 'Joint Sitting' in source.name \
            and Sitting.objects.filter(
                    venue=venue,
                    source__name=source.name,
                    start_date=source.date,
                    start_time=data['meta'].get('start_time', None)
                ).exists():
            print "skipping duplicate source %s for %s" % (source.name, source.date)
            return None

        sitting = Sitting(
            source     = source,
            venue      = venue,
            start_date = source.date,
            start_time = data['meta'].get('start_time', None),
            end_date   = source.date,
            end_time   = data['meta'].get('end_time', None),
        )
        sitting.save()

        with transaction.atomic():
            counter = 0
            for line in data['transcript']:

                counter += 1

                entry = Entry(
                    sitting       = sitting,
                    type          = line['type'],
                    page_number   = line['page_number'],
                    text_counter  = counter,
                    speaker_name  = line.get('speaker_name',  ''),
                    speaker_title = line.get('speaker_title', ''),
                    content       = line['text'],
                )
                entry.save()

            source.last_processing_success = datetime.datetime.now()
            source.save()

        return None
