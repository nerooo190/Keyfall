"""Turn messy MIDI filenames into (artist, title, version, arranger, category)."""
import re
import unicodedata

ARRANGERS = [
    (r"\(?\bpianoitall(?:\.com)?\)?", "Pianoitall"),
    (r"\[rousseau cover midi\]", "Rousseau"),
    (r"\(atlantic lights arrangement[^)]*\)", "Atlantic Lights"),
    (r"\(adrian lee piano version\)", "Adrian Lee"),
    (r"\(evan duffy piano version\)", "Evan Duffy"),
    (r"\bpiano\s*-\s*rinerion\b|\s-\s*rinerion\b", "Rinerion"),
    (r"arr\. by fonzi m|fonzimgm|piano by fonzi m remastered for upload", "Fonzi M"),
    (r"\(lsanonymous300\)", "LSAnonymous300"),
]
VERSIONS = [
    (r"\((?:hard version|hard)\)", "Hard"),
    (r"\(harder\)", "Hard"),
    (r"\(advanced\)", "Advanced"),
    (r"\(simple\)", "Simple"),
    (r"\(beginner\)", "Beginner"),
    (r"\s-\s*easy\b|\beasy piano\b|\beasy\b", "Easy"),
    (r"\bintermediate piano solo\b", "Intermediate"),
]
JUNK = [
    r"\[midicollection\.net\]", r"\(hands are divided?\)", r"\(\d\)", r"\(2\)mid", r"\b41k\b",
    r"\bformat0\b", r"^full midi\s*-\s*", r"^midi file\s*-\s*", r"\bmidi\b$", r"\bpiano cover\b",
    r"\bpiano solo\b", r"\bpiano tutorial\b", r"\bin c major\b",
]

# Files whose names are ambiguous or missing the artist: stem -> (artist, title[, version])
OVERRIDES = {
    "5 Beautiful songs (hands are divided)": ("Various", "5 Beautiful Songs (Medley)"),
    "50 Ways to Say Goodbye": ("Train", "50 Ways to Say Goodbye"),
    "A Thousand Miles": ("Vanessa Carlton", "A Thousand Miles"),
    "Adam's Song - Blink 182 - Rinerion": ("Blink-182", "Adam's Song"),
    "Africa_-_Toto": ("Toto", "Africa"),
    "Alan_Walker_Faded": ("Alan Walker", "Faded"),
    "Alan-Walker-K-391-IGNITE-MIDI": ("K-391 & Alan Walker", "Ignite"),
    "All of Me": ("John Legend", "All of Me"),
    "Alone - Alan Walker (hands are divided)": ("Alan Walker", "Alone"),
    "as_time_goes_by": ("Herman Hupfeld", "As Time Goes By"),
    "Bad Romance Midi": ("Lady Gaga", "Bad Romance"),
    "Beethoven_Symphony_No7": ("Ludwig van Beethoven", "Symphony No. 7"),
    "beliver": ("Imagine Dragons", "Believer"),
    "blink-182_All_the_small_things_MIDI": ("Blink-182", "All the Small Things"),
    "brahms_opus1_1_format0": ("Johannes Brahms", "Piano Sonata No. 1, Op. 1 – I. Allegro"),
    "brahms_opus1_2_format0": ("Johannes Brahms", "Piano Sonata No. 1, Op. 1 – II. Andante"),
    "brahms_opus1_3_format0": ("Johannes Brahms", "Piano Sonata No. 1, Op. 1 – III. Scherzo"),
    "brahms_opus1_4_format0": ("Johannes Brahms", "Piano Sonata No. 1, Op. 1 – IV. Finale"),
    "break_free_-_ariana_grande_feat._zedd_arr._by_fonzi_m": ("Ariana Grande feat. Zedd", "Break Free"),
    "bruce_hornsby-the_way_it_is": ("Bruce Hornsby", "The Way It Is"),
    "Call Me Maybe - Carly Rae Jepsen [MIDICollection.net]": ("Carly Rae Jepsen", "Call Me Maybe"),
    "cee_lo_green-forget_you": ("CeeLo Green", "Forget You"),
    "Children": ("Robert Miles", "Children"),
    "coldplay-a_sky_full_of_stars": ("Coldplay", "A Sky Full of Stars"),
    "Davy Jones": ("Hans Zimmer", "Davy Jones"),
    "Daybreak - Piano Solo in C Major": ("Unknown", "Daybreak"),
    "deep end (hands are divided)": ("Birdy", "Deep End"),
    "Demons (LSAnonymous300)": ("Imagine Dragons", "Demons"),
    "Die_For_You": ("The Weeknd", "Die For You"),
    "Drink Up Me Hearties": ("Hans Zimmer", "Drink Up Me Hearties"),
    "Ed_Sheeran_Perfect_Piano_Cover": ("Ed Sheeran", "Perfect"),
    "elise_format0": ("Ludwig van Beethoven", "Für Elise"),
    "Euphemia_Allen_Chopsticks": ("Euphemia Allen", "Chopsticks"),
    "Everybody Talks": ("Neon Trees", "Everybody Talks"),
    "Experience_-_Ludovico_Einaudi": ("Ludovico Einaudi", "Experience"),
    "Faded": ("Alan Walker", "Faded"),
    "Fall For You - Second Hand Serenade": ("Secondhand Serenade", "Fall for You"),
    "Farewell Hyrule King": ("Koji Kondo", "Farewell Hyrule King"),
    "Feed_Me_+_Ellie_Goulding_-_Relocating_The_Lights_(Evan_Duffy_Piano_Version)": ("Feed Me & Ellie Goulding", "Relocating the Lights"),
    "Fur_Elise": ("Ludwig van Beethoven", "Für Elise"),
    "Game_of_Thrones_Easy_piano": ("Ramin Djawadi", "Game of Thrones – Main Theme", "Easy"),
    "Game_of_Thrones_Main_Theme": ("Ramin Djawadi", "Game of Thrones – Main Theme"),
    "Gary Jules - Mad World": ("Gary Jules", "Mad World"),
    "Good_bad_ugly": ("Ennio Morricone", "The Good, the Bad and the Ugly"),
    "Gravity_Falls_Opening_-_Intermediate_Piano_Solo": ("Brad Breeck", "Gravity Falls – Opening", "Intermediate"),
    "Green Day - Good Riddence (Advanced)": ("Green Day", "Good Riddance (Time of Your Life)", "Advanced"),
    "Green Day - Good Riddence (Beginner)": ("Green Day", "Good Riddance (Time of Your Life)", "Beginner"),
    "Hall of Fame - The Script [MIDICollection.net]": ("The Script", "Hall of Fame"),
    "Happy Birthday - Chopin and Liszt style": ("Traditional", "Happy Birthday (Chopin & Liszt Style)"),
    "Hedwig's Theme": ("John Williams", "Hedwig's Theme"),
    "He's a Pirate - Pirates of the Caribbean [MIDICollection.net]": ("Klaus Badelt", "He's a Pirate"),
    "He's a Pirate": ("Klaus Badelt", "He's a Pirate"),
    "Hotel California": ("Eagles", "Hotel California"),
    "HTTYD - See You Tomorrow": ("John Powell", "See You Tomorrow (How to Train Your Dragon)"),
    "Imagine": ("John Lennon", "Imagine"),
    "Imogen_Heap_-_Hide_And_Seek": ("Imogen Heap", "Hide and Seek"),
    "Inception - Time": ("Hans Zimmer", "Time (Inception)"),
    "Interstellar": ("Hans Zimmer", "Interstellar – Main Theme"),
    "Israel IZ Kamakawiwo'ole - Somewhere over the Rainbow - EASY": ("Israel Kamakawiwoʻole", "Somewhere Over the Rainbow", "Easy"),
    "Johann Sebastian Bach - 1st Prelude - EASY": ("Johann Sebastian Bach", "Prelude in C Major, BWV 846", "Easy"),
    "keiko_matsui_midnight_stone": ("Keiko Matsui", "Midnight Stone"),
    "Les Adieux 1st Movement": ("Ludwig van Beethoven", "Sonata No. 26 \"Les Adieux\" – I."),
    "Les Adieux 2nd Movement": ("Ludwig van Beethoven", "Sonata No. 26 \"Les Adieux\" – II."),
    "les_choristes_cerf_volant": ("Bruno Coulais", "Cerf-volant (Les Choristes)"),
    "les_choristes_vois_sur_ton_chemin1": ("Bruno Coulais", "Vois sur ton chemin (Les Choristes)"),
    "Let Her Go - Passenger [MIDICollection.net]": ("Passenger", "Let Her Go"),
    "Let me down slowly (hands are divided)": ("Alec Benjamin", "Let Me Down Slowly"),
    "Let_Her_Go_Passenger": ("Passenger", "Let Her Go"),
    "Liebestraum_No._3_in_A_Major": ("Franz Liszt", "Liebestraum No. 3"),
    "Lost Woods": ("Koji Kondo", "Lost Woods"),
    "Love_Story_-_Where_Do_I_Begin": ("Francis Lai", "Love Story (Where Do I Begin)"),
    "Andy Williams - Love Story Where Do I Begin": ("Andy Williams", "Love Story (Where Do I Begin)"),
    "Lovely by Sawser Natho": ("Billie Eilish & Khalid", "Lovely"),
    "Ludwig Van Beethoven - Sonata No.14 Op.27 - Sonata Quasi Una Fantasia - Moonlight Sonata": ("Ludwig van Beethoven", "Moonlight Sonata (Sonata No. 14, Op. 27)"),
    "Ludwig Van Beethoven - Sonate No. 17, Tempest, 3rd Movement": ("Ludwig van Beethoven", "Sonata No. 17 \"Tempest\" – III."),
    "Mad World - Gary Jules": ("Gary Jules", "Mad World"),
    "Mad world (hands are divided)": ("Gary Jules", "Mad World"),
    "mak - idk (hands are divided)": ("mak", "idk"),
    "MIDI File - Hans Zimmer - Interstellar (Atlantic Lights Arrangement + Tempo + Key + Colors)": ("Hans Zimmer", "Interstellar"),
    "Metallica_-_Nothing_Else_Matters_piano_solo": ("Metallica", "Nothing Else Matters"),
    "Monday - Ludovico Einaudi (2)mid": ("Ludovico Einaudi", "Monday"),
    "Monday - Ludovico Einaudi": ("Ludovico Einaudi", "Monday"),
    "Mozart - Sonata No. 16, 1st Movement K. 545": ("Wolfgang Amadeus Mozart", "Piano Sonata No. 16, K. 545 – I."),
    "My_Life_Is_going_on_-_La_casa_de_papel": ("Cecilia Krull", "My Life Is Going On (La Casa de Papel)"),
    "night_2_is_ee_the_stars": ("Unknown", "Night 2 (The Stars)"),
    "nocturne_9_2": ("Frédéric Chopin", "Nocturne Op. 9 No. 2"),
    "One Day": ("Hans Zimmer", "One Day"),
    "Owl City - Fireflies  PIANO - Rinerion": ("Owl City", "Fireflies"),
    "Panic! At The Disco- GirlsGirlsBoys": ("Panic! at the Disco", "Girls/Girls/Boys"),
    "Paparazzi": ("Lady Gaga", "Paparazzi"),
    "Paradise": ("Coldplay", "Paradise"),
    "passenger-let_her_go": ("Passenger", "Let Her Go"),
    "Peter Tschaikowsky (Die Jahreszeiten) - April": ("Pyotr Ilyich Tchaikovsky", "The Seasons – April"),
    "Peter Tschaikowsky (Die Jahreszeiten) - August": ("Pyotr Ilyich Tchaikovsky", "The Seasons – August"),
    "Peter Tschaikowsky (Die Jahreszeiten) - Dezember": ("Pyotr Ilyich Tchaikovsky", "The Seasons – December"),
    "Peter Tschaikowsky (Die Jahreszeiten) - Februar": ("Pyotr Ilyich Tchaikovsky", "The Seasons – February"),
    "Peter Tschaikowsky (Die Jahreszeiten) - Januar": ("Pyotr Ilyich Tchaikovsky", "The Seasons – January"),
    "Peter Tschaikowsky (Die Jahreszeiten) - Juli": ("Pyotr Ilyich Tchaikovsky", "The Seasons – July"),
    "Peter Tschaikowsky (Die Jahreszeiten) - Juni": ("Pyotr Ilyich Tchaikovsky", "The Seasons – June"),
    "Piano Quick Riff - Last Christmas": ("Wham!", "Last Christmas (Quick Riff)"),
    "Piano_Man_Piano": ("Billy Joel", "Piano Man"),
    "Piano_See_You_Again_Wiz_Khalifa": ("Wiz Khalifa feat. Charlie Puth", "See You Again"),
    "Pixies Where is my mind PIANO - Rinerion": ("Pixies", "Where Is My Mind?"),
    "Plain White Tea's - Hey There Delilah": ("Plain White T's", "Hey There Delilah"),
    "Pompeii": ("Bastille", "Pompeii"),
    "radioactiv": ("Imagine Dragons", "Radioactive"),
    "Rain": ("Unknown", "Rain"),
    "Requiem_for_a_Dream_Easy": ("Clint Mansell", "Requiem for a Dream – Lux Aeterna", "Easy"),
    "RHCP - Under The Bridge": ("Red Hot Chili Peppers", "Under the Bridge"),
    "River Flows in You - Yiruma [MIDICollection.net]": ("Yiruma", "River Flows in You"),
    "River Flows in You": ("Yiruma", "River Flows in You"),
    "River_Flows_In_You": ("Yiruma", "River Flows in You"),
    "Roar": ("Katy Perry", "Roar"),
    "Rocket Man": ("Elton John", "Rocket Man"),
    "roxette-listen_to_your_heart": ("Roxette", "Listen to Your Heart"),
    "sao2_-_ed_startear_piano_by_fonzi_m_remastered_for_upload": ("Luna Haruna", "Startear (Sword Art Online II ED)"),
    "sara_bareilles-love_song": ("Sara Bareilles", "Love Song"),
    "See_You_Again_-_Wiz_Khalifa__Charlie_Puth_Piano_Tutorial_": ("Wiz Khalifa feat. Charlie Puth", "See You Again"),
    "See_You_Again_no_rap": ("Wiz Khalifa feat. Charlie Puth", "See You Again (No Rap)"),
    "See_You_Again_Wiz_Khalifa_Charlie_Puth_Piano_Tutorial": ("Wiz Khalifa feat. Charlie Puth", "See You Again"),
    "Sergei Rachmaninoff - Rhapsody on a Theme of Paganini - Variation 18": ("Sergei Rachmaninoff", "Rhapsody on a Theme of Paganini – Variation 18"),
    "ses_Death": ("Unknown", "Death"),
    "Skyfall": ("Adele", "Skyfall"),
    "Someone you loved": ("Lewis Capaldi", "Someone You Loved"),
    "Sonate_No._14_Moonlight_1st_Movement": ("Ludwig van Beethoven", "Moonlight Sonata – I."),
    "Sonate_No._14_Moonlight_3rd_Movement": ("Ludwig van Beethoven", "Moonlight Sonata – III."),
    "Sonatina Opus 36 No. 2 1st Movement": ("Muzio Clementi", "Sonatina Op. 36 No. 2 – I."),
    "Song of Storms": ("Koji Kondo", "Song of Storms"),
    "Stairway_To_Heaven": ("Led Zeppelin", "Stairway to Heaven"),
    "Stairway_to_Heaven_-_Led_Zeppelin": ("Led Zeppelin", "Stairway to Heaven"),
    "Star Wars Main Theme": ("John Williams", "Star Wars – Main Theme"),
    "stay_the_night_-_zedd_ft._hayley_williams_fonzimgm": ("Zedd feat. Hayley Williams", "Stay the Night"),
    "Still_Dre_-_Dr._Dre_and_Snoop_Dogg": ("Dr. Dre feat. Snoop Dogg", "Still D.R.E."),
    "Still_Dre_Composition": ("Dr. Dre feat. Snoop Dogg", "Still D.R.E."),
    "Dr Dre - Still Dre": ("Dr. Dre feat. Snoop Dogg", "Still D.R.E."),
    "Summertime_Sadness": ("Lana Del Rey", "Summertime Sadness"),
    "Super Mario Theme-Pianoitall": ("Koji Kondo", "Super Mario Bros. Theme"),
    "Super_Mario_Bros._-_Main_Theme": ("Koji Kondo", "Super Mario Bros. Theme"),
    "Tchaikovsky_Piano_Concerto_No1": ("Pyotr Ilyich Tchaikovsky", "Piano Concerto No. 1"),
    "The Black Pearl": ("Klaus Badelt", "The Black Pearl"),
    "The Blood Ritual and Moonlight Serenade": ("Hans Zimmer", "The Blood Ritual / Moonlight Serenade"),
    "The Final Countdown": ("Europe", "The Final Countdown"),
    "The Imperial March": ("John Williams", "The Imperial March"),
    "The Knacks - My Sharona (Advanced)": ("The Knack", "My Sharona", "Advanced"),
    "The Pink Pather Theme (1)": ("Henry Mancini", "The Pink Panther Theme"),
    "The Pink Pather Theme": ("Henry Mancini", "The Pink Panther Theme"),
    "The_Office__Opening_Theme": ("Jay Ferguson", "The Office – Opening Theme"),
    "The-Daydream-Tears": ("The Daydream", "Tears"),
    "THIS": ("Unknown", "This"),
    "Ti_Amo": ("Unknown", "Ti Amo"),
    "Time - Zimmer (hands are divided)": ("Hans Zimmer", "Time (Inception)"),
    "Titanic": ("James Horner", "My Heart Will Go On (Titanic)"),
    "Titanium": ("David Guetta feat. Sia", "Titanium"),
    "train-drops_of_jupiter": ("Train", "Drops of Jupiter"),
    "Turret Opera (Cara Mia) - SATB": ("Jonathan Coulton", "Cara Mia Addio (Turret Opera)"),
    "Unravel_Animenz_-_Toyko_Ghoul": ("TK from Ling tosite sigure", "Unravel (Tokyo Ghoul OP)"),
    "Up is Down": ("Hans Zimmer", "Up Is Down"),
    "Voletarium_Countdown": ("Unknown", "Voletarium Countdown"),
    "Waltz_No._2_by_Shostakovich": ("Dmitri Shostakovich", "Waltz No. 2"),
    "Where is my mind (hands are divided)": ("Pixies", "Where Is My Mind?"),
    "wounderful_world": ("Louis Armstrong", "What a Wonderful World"),
    "Yann_Tiersen_-_Comptine_Dun_Autre_Ete__Lapres_Midi": ("Yann Tiersen", "Comptine d'un autre été – L'après-midi"),
    "yann_tiersen-comptine_dun_autre_ete": ("Yann Tiersen", "Comptine d'un autre été – L'après-midi"),
    "Yann Tiersen - Comptine dun autre ete": ("Yann Tiersen", "Comptine d'un autre été – L'après-midi"),
    "Zelda's Lullaby": ("Koji Kondo", "Zelda's Lullaby"),
    "Euphemia Allen Chopsticks": ("Euphemia Allen", "Chopsticks"),
    "Evanscence - Bring Me To Life": ("Evanescence", "Bring Me to Life"),
    "Katy Perry - Et": ("Katy Perry", "E.T."),
    "Katy perry - Last Friday Night": ("Katy Perry", "Last Friday Night"),
    "Pirates of the Caribbean - Davy Jones": ("Hans Zimmer", "Davy Jones"),
    "Pirates of the Caribbean - He's a Pirate": ("Klaus Badelt", "He's a Pirate"),
    "Pokemon - Theme": ("Jason Paige", "Pokémon Theme"),
    "Harry Potter - Medley": ("John Williams", "Harry Potter Medley"),
    "Super Mario World - Underwater Theme": ("Koji Kondo", "Super Mario World – Underwater Theme"),
    "Transformers Theme (2007)": ("Steve Jablonsky", "Transformers Theme (2007)"),
    "True Colors - Coeur de Pirate": ("Cœur de pirate", "True Colors"),
    "Tegan and Sara - Everything Is Awesome (The LEGO Movie)": ("Tegan and Sara", "Everything Is Awesome"),
    "Yann Tiersen -Valse d'Amélie": ("Yann Tiersen", "La Valse d'Amélie"),
    "Ludwig van Beethoven - Für Elise": ("Ludwig van Beethoven", "Für Elise"),
    "Michel Teló - Ai Se Eu Te Pego": ("Michel Teló", "Ai Se Eu Te Pego"),
    "Coolio - Gangsta's Paradise [Remake] (hands are divided)": ("Coolio", "Gangsta's Paradise (Remake)"),
    "Ed Sheeran - Autumn Leaves (Advanced)": ("Ed Sheeran", "Autumn Leaves", "Advanced"),
    "Zedd ft. Foxes - Clarity (Pianoitall.com)": ("Zedd feat. Foxes", "Clarity"),
    "30 Seconds 2 Mars - Bright Lights": ("Thirty Seconds to Mars", "Bright Lights"),
    "30 Seconds 2 Mars - City Of Angels": ("Thirty Seconds to Mars", "City of Angels"),
    "30 Seconds To Mars - This Is War": ("Thirty Seconds to Mars", "This Is War"),
    "5sos - Heartbreak Girl - Pianoitall": ("5 Seconds of Summer", "Heartbreak Girl"),
    "Imagine Dragons x J.I.D - Enemy (hands are divide)": ("Imagine Dragons x J.I.D", "Enemy"),
    "BLACKPINCK - How You Like That (hands are divided)": ("BLACKPINK", "How You Like That"),
    "Kina - Get you the moon (hands are divided)": ("Kina", "Get You the Moon"),
    "Hozier - take me to church (hands are divided)": ("Hozier", "Take Me to Church"),
    "Adele - hello (hands are divided)": ("Adele", "Hello"),
    "Tom Odell - Another love (hands are divided)": ("Tom Odell", "Another Love"),
    "Imagine Dragons - Follow you (hands are divided)": ("Imagine Dragons", "Follow You"),
    "Linkin park - Numb": ("Linkin Park", "Numb"),
    "Bruno Mars - Talking to the moon (hands are divided)": ("Bruno Mars", "Talking to the Moon"),
    "Serhat Durmus - La Câlin": ("Serhat Durmus", "La Câlin"),
    "Ennio Morricone - Chi Mai": ("Ennio Morricone", "Chi Mai"),
    "Eric Thiman - Flood Time": ("Eric Thiman", "Flood Time"),
    "Franz Liszt - Liebestraum No. 3": ("Franz Liszt", "Liebestraum No. 3"),
    "Johann Pachelbel - Canon in D": ("Johann Pachelbel", "Canon in D"),
    "Christina Perri - Human (Hard)": ("Christina Perri", "Human", "Hard"),
    "Hans Zimmer - First Step - Interstellar": ("Hans Zimmer", "First Step (Interstellar)"),
    "Tuukka Jokilehto - A Love Story - EASY": ("Tuukka Jokilehto", "A Love Story", "Easy"),
    "Lily Allen - Hard Out Here (Hard)": ("Lily Allen", "Hard Out Here", "Hard"),
    "Linkin Park  - Faint": ("Linkin Park", "Faint"),
    "Far East Movement  - Rocketeer": ("Far East Movement", "Rocketeer"),
    "Martin Solveig ft. Dragonette - Hello ": ("Martin Solveig feat. Dragonette", "Hello"),
    "Rihanna - Whats My Name ft Drake": ("Rihanna feat. Drake", "What's My Name?"),
    "Magic System - Magic In The Air Feat. Chawki": ("Magic System feat. Chawki", "Magic in the Air"),
    "Pitbull - Castle Made Of Sand feat. Kelly Rowland & Jamie Drastik": ("Pitbull feat. Kelly Rowland & Jamie Drastik", "Castle Made of Sand"),
    "Yann Tiersen - La Noyée": ("Yann Tiersen", "La Noyée"),
    "Despacito_Piano_Sheet_Music_Luis_Fonsi_ft_Daddy_Yankee": ("Luis Fonsi feat. Daddy Yankee", "Despacito"),
    "Taylor Swift - we are never getting back together": ("Taylor Swift", "We Are Never Ever Getting Back Together"),
    "Swedish House Mafia - Dont You Worry Child (Advanced)": ("Swedish House Mafia", "Don't You Worry Child", "Advanced"),
    "Rocket Man 41k": ("Elton John", "Rocket Man"),
}

ARTIST_ALIASES = {
    "QUEEN": "Queen", "Beatles": "The Beatles", "Beethoven": "Ludwig van Beethoven",
    "Billie Eilish, Khalid": "Billie Eilish & Khalid", "T.I": "T.I.", "Pink": "P!nk",
}

CLASSICAL = ["beethoven", "brahms", "chopin", "mozart", "liszt", "bach", "pachelbel", "tchaikovsky",
             "rachmaninoff", "clementi", "shostakovich", "euphemia allen", "eric thiman", "traditional"]
NEOCLASSICAL = ["einaudi", "yiruma", "yann tiersen", "keiko matsui", "serhat durmus", "tuukka", "daybreak"]
FILM_TV = ["hans zimmer", "john williams", "klaus badelt", "james horner", "ramin djawadi", "ennio morricone",
           "henry mancini", "jay ferguson", "brad breeck", "bruno coulais", "francis lai", "clint mansell",
           "john powell", "steve jablonsky", "cecilia krull", "luna haruna", "tk from", "jason paige",
           "tegan and sara", "herman hupfeld"]
GAMES = ["koji kondo", "jonathan coulton", "zelda", "mario", "pokemon"]


def category(artist, title):
    a = (artist + " " + title).lower()
    for keys, name in ((GAMES, "Video Games"), (FILM_TV, "Film & TV"), (CLASSICAL, "Classical"),
                       (NEOCLASSICAL, "Modern Piano")):
        if any(re.search(r"\b" + re.escape(k) + r"\b", a) for k in keys):
            return name
    if "zelda ocarina" in a:
        return "Video Games"
    return "Pop & Rock"


def _tidy(s):
    s = re.sub(r"\s+", " ", s).strip(" -_.")
    return s


def parse(stem):
    """Return dict(artist, title, version, arranger, category, split_hands)."""
    stem = unicodedata.normalize("NFC", stem)
    low = stem.lower()
    arranger = next((name for pat, name in ARRANGERS if re.search(pat, low)), "")
    if "animenz" in low:
        arranger = "Animenz"
    split = bool(re.search(r"hands are divid", low))
    version = ""
    for pat, name in VERSIONS:
        if re.search(pat, low):
            version = name
            break

    if stem in OVERRIDES:
        o = OVERRIDES[stem]
        artist, title = o[0], o[1]
        version = o[2] if len(o) > 2 else version
    else:
        s = stem.replace("_", " ")
        for pat, _ in ARRANGERS:
            s = re.sub(pat, "", s, flags=re.I)
        for pat, _ in VERSIONS:
            s = re.sub(pat, "", s, flags=re.I)
        for pat in JUNK:
            s = re.sub(pat, "", s, flags=re.I)
        s = _tidy(s)
        if s.lower().startswith("zelda ocarina of time - "):
            artist, title = "Koji Kondo", s.split(" - ", 1)[1]
            title = title.replace("Zeldas", "Zelda's").replace("Ganondorfs", "Ganondorf's") \
                         .replace("Sheiks", "Sheik's").replace("Zoras", "Zora's").replace("Trees", "Tree's")
            title += " (Ocarina of Time)"
        elif " - " in s:
            artist, title = s.split(" - ", 1)
        else:
            artist, title = "Unknown", s
        artist, title = _tidy(artist), _tidy(title)
        artist = re.sub(r"\bft\.?\s", "feat. ", artist)
        artist = re.sub(r"\bfeat\s", "feat. ", artist)
    artist = ARTIST_ALIASES.get(artist, artist)
    return {
        "artist": artist,
        "title": title,
        "version": version,
        "arranger": arranger,
        "category": category(artist, title),
        "split_hands": split,
    }


if __name__ == "__main__":
    import os
    import sys
    for dp, _, fs in os.walk(sys.argv[1]):
        for f in sorted(fs):
            r = parse(os.path.splitext(f)[0])
            print(f"{r['category'][:5]:5} | {r['artist'][:30]:30} | {r['title'][:45]:45} | {r['version']:12} | {r['arranger']}")
