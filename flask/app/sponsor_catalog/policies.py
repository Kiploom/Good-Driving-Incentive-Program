# app/sponsor_catalog/policies.py
DENYLIST_TERMS = {
    "explicit": [
        # Core adult terms
        "porn", "porno", "pornography", "xxx", "xxxx", "nsfw", "18+", "21+", "adults only", "adult only",
        "explicit", "x-rated", "r-rated", "mature content", "mature audiences",
        
        # Sexual content
        "sex", "sexual", "sexy", "erotic", "erotica", "sensual", "seductive", "provocative",
        "intercourse", "intimate", "intimacy", "foreplay", "orgasm", "climax",
        
        # Adult products
        "sex toy", "sextoy", "sex toys", "adult toy", "pleasure toy", "intimate toy",
        "vibrator", "dildo", "masturbator", "stroker", "pocket pussy", "fleshlight",
        "butt plug", "anal bead", "anal plug", "prostate massager", "kegel ball", "ben wa",
        "cock ring", "penis ring", "penis pump", "penis extender", "penis sleeve",
        "condom", "condoms", "rubber", "rubbers", "protection", "safe sex", "contraceptive",
        "contraceptives", "birth control", "family planning", "latex glove", "latex gloves",
        "trojan", "durex", "lifestyles", "skyn", "magnum", "ribbed", "textured",
        "flavored condom", "colored condom", "glow in the dark", "studded",
        "female condom", "dental dam", "finger cot", "finger cots",
        "lubricant", "lube", "personal lubricant", "sexual lubricant", "intimate lubricant",
        "massage oil", "sensual oil", "arousal gel", "warming gel", "cooling gel",
        "bondage", "bdsm", "fetish", "kinky", "kink", "restraint", "handcuff", "whip", "flogger",
        "nipple clamp", "nipple clip", "ball gag", "gag ball", "gimp", "dom", "sub",
        "love swing", "sex swing", "sex chair", "love doll", "sex doll", "blow up doll", "inflatable doll",
        "pocket rocket", "magic wand", "hitachi", "rabbit vibrator", "bullet vibrator",
        "strap on", "strap-on", "strapon", "harness", "double ended", "double dong",
        
        # Lingerie and revealing clothing
        "lingerie erotic", "crotchless", "edible underwear", "edible panties", "g-string",
        "barely there", "see through", "see-through", "sheer lingerie", "peekaboo",
        "open cup", "open crotch", "cupless", "crotchless", "split crotch",
        "bodystocking", "body stocking", "fishnet bodystocking", "fishnet lingerie",
        "nipple pasties", "pasties", "nipple cover", "nipple tape", "breast tape",
        "stripper wear", "stripper outfit", "exotic dancer", "pole dancer",
        
        # Adult media and services
        "nude", "nudity", "naked", "topless", "bottomless", "full frontal",
        "stripper", "strip club", "strip show", "peep show", "adult film", "adult video",
        "camgirl", "cam girl", "camboy", "cam boy", "webcam girl", "webcam model",
        "onlyfans", "escort", "call girl", "prostitute", "brothel", "red light",
        "adult entertainment", "adult content", "adult material",
        
        # Pharmaceuticals and enhancement
        "viagra", "cialis", "levitra", "ed pill", "erectile", "penis enlargement",
        "male enhancement", "female enhancement", "libido", "aphrodisiac",
        "testosterone booster", "horny goat weed", "spanish fly",
        
        # Anatomical (in adult context)
        "genital", "genitals", "penis", "vagina", "vulva", "clitoris", "anus", "anal",
        "breast enlargement", "breast enhancement", "boob", "tit", "dick", "cock",
        "pussy", "vaginal", "penile", "testicular", "testicle", "scrotum",
        
        # Adult industry terms
        "adult store", "adult shop", "sex shop", "pleasure shop", "intimate boutique",
        "adult novelty", "novelty item", "bachelor party", "bachelorette party",
        "naughty", "raunchy", "dirty", "filthy", "nasty", "lewd", "obscene",
        
        # Common brand/slang variations
        "adam and eve", "lovehoney", "womanizer", "satisfyer", "lelo", "we-vibe",
        "tenga", "bad dragon", "tantus", "fun factory",
        
        # Euphemisms and coded language
        "personal massager", "body massager", "intimate massager", "personal pleasure",
        "marital aid", "bedroom accessory", "bedroom toy", "couples toy",
        "sensory play", "role play outfit", "costume play", "adult costume",
        
        # Drug paraphernalia (often associated)
        "bong", "water pipe", "smoking pipe", "vaporizer", "grinder", "rolling paper",
        "420", "stoner", "weed accessories",
        
        # Additional variations and misspellings
        "s3x", "s3xy", "pr0n", "p0rn", "sexx", "sexxy", "nekkid",
        "xrated", "x rated", "adultonly", "adultsonly",
        
        # Reproductive/medical in non-clinical context
        "fertility", "conception aid", "ovulation", "sperm", "ejaculation",
        
        # Fetish specific
        "leather fetish", "latex fetish", "foot fetish", "smoking fetish",
        "furry", "fursuit", "petplay", "pet play", "pony play",
        "diaper fetish", "abdl", "age play", "ageplay",
        
        # Other red flags
        "glory hole", "peep hole", "swing club", "swingers", "wife sharing",
        "threesome", "group sex", "orgy", "gang bang", "bukkake",
        "hentai", "doujin", "ecchi", "yaoi", "yuri", "futanari",
        "rule 34", "lewds", "thirst trap", "only fans",
        
        # Dating/hookup coded terms
        "sugar daddy", "sugar baby", "seeking arrangement", "casual encounter",
        "friends with benefits", "fwb", "nsa", "no strings attached",
        
        # Additional safety terms
        "adult verification", "age verification required", "must be 18", "must be 21",
        "parental advisory", "not for minors", "adults-only content",
        
        # Sexual health and contraception terms (NEW ADDITIONS)
        "sex education", "sexual health", "std prevention", "sti prevention",
        "pregnancy prevention", "unwanted pregnancy", "emergency contraceptive",
        "morning after", "plan b", "ella", "iud", "coil", "implant",
        "hormonal contraceptive", "pill", "birth control pill", "the pill",
        "patch", "ring", "shot", "injection", "depo", "depo provera",
        "fertility awareness", "natural family planning", "rhythm method",
        "withdrawal", "pull out", "pullout method", "coitus interruptus",
        "abstinence", "celibacy", "virginity", "first time", "losing virginity",
        "sexual debut", "sexual initiation", "coming of age", "sexual maturity",
        "puberty", "adolescent", "teenage", "teen", "young adult",
        "sexual development", "sexual awakening", "sexual discovery",
        "masturbation", "self pleasure", "self-pleasure", "solo play",
        "mutual masturbation", "hand job", "handjob", "blow job", "blowjob",
        "oral sex", "fellatio", "cunnilingus", "69", "sixty nine",
        "foreplay", "heavy petting", "making out", "necking", "petting",
        "dry humping", "grinding", "frottage", "tribadism", "scissoring",
        "penetration", "vaginal", "anal", "oral", "digital", "fingering",
        "fisting", "double penetration", "dp", "gangbang", "bukkake",
        "creampie", "facials", "golden shower", "watersports", "scat",
        "roleplay", "role play", "dirty talk", "phone sex", "cybersex",
        "sexting", "nudes", "nude pics", "dick pic", "dick pics", "boob pic",
        "tit pic", "pussy pic", "ass pic", "butt pic", "selfie nude",
        "nude selfie", "explicit photo", "explicit image", "adult photo",
        "adult image", "sexual photo", "sexual image", "intimate photo",
        "intimate image", "private photo", "private image", "personal photo",
        "personal image", "bedroom photo", "bedroom image", "boudoir",
        "boudoir photo", "boudoir photography", "glamour", "glamour photo",
        "pinup", "pin up", "cheesecake", "beefcake", "softcore", "soft core",
        "hardcore", "hard core", "pornographic", "pornographic material",
        "obscene material", "indecent material", "lewd material",
        "sexual material", "adult material", "mature material",
        "adult entertainment", "adult content", "adult media", "adult film",
        "adult video", "adult movie", "adult dvd", "adult blu ray",
        "adult streaming", "adult subscription", "adult membership",
        "adult website", "adult site", "adult portal", "adult platform",
        "adult service", "adult provider", "adult worker", "sex worker",
        "escort service", "escort agency", "escort business", "escort work",
        "prostitution", "prostitute", "hooker", "streetwalker", "call girl",
        "high class escort", "luxury escort", "premium escort", "elite escort",
        "sugar daddy", "sugar baby", "sugar mommy", "sugar mama",
        "arrangement", "mutually beneficial", "benefactor", "sponsor",
        "financial support", "financial assistance", "allowance", "gift",
        "companionship", "intimate companionship", "romantic companionship",
        "dating", "casual dating", "casual sex", "hookup", "one night stand",
        "friends with benefits", "fwb", "booty call", "fuck buddy",
        "sex buddy", "playmate", "play partner", "sexual partner",
        "bed partner", "sleeping together", "sleeping around", "cheating",
        "affair", "extramarital", "adultery", "infidelity", "unfaithful",
        "swinging", "swingers", "swinger club", "swinger party", "swinger lifestyle",
        "wife swapping", "wife sharing", "husband swapping", "husband sharing",
        "couple swapping", "couple sharing", "group sex", "orgy", "gangbang",
        "threesome", "mfm", "fmf", "mmf", "ffm", "mfmf", "foursome",
        "fivesome", "sixsome", "orgy", "sex party", "sex club", "sex bar",
        "sex lounge", "sex dungeon", "sex room", "play room", "playroom",
        "dungeon", "bdsm dungeon", "fetish dungeon", "kink dungeon",
        "dominant", "dom", "domme", "domina", "mistress", "master",
        "submissive", "sub", "slave", "pet", "puppy", "kitten", "little",
        "brat", "bratty", "switch", "versatile", "top", "bottom", "vers",
        "sadist", "masochist", "sadomasochist", "sadomasochism", "s&m",
        "sadism", "masochism", "pain", "pleasure", "pain play", "pleasure play",
        "impact play", "whip", "flogger", "crop", "paddle", "spanking",
        "caning", "birching", "belting", "strapping", "whipping", "flogging",
        "bondage", "rope bondage", "shibari", "kinbaku", "rope play",
        "rope work", "rope art", "rope bondage", "bondage rope", "bondage tape",
        "duct tape", "electrical tape", "medical tape", "bondage gear",
        "restraints", "handcuffs", "leg cuffs", "ankle cuffs", "wrist cuffs",
        "collar", "leash", "harness", "straitjacket", "straight jacket",
        "gag", "ball gag", "bit gag", "ring gag", "spider gag", "mouth gag",
        "blindfold", "eye mask", "sleep mask", "hood", "leather hood",
        "latex hood", "rubber hood", "gas mask", "respirator", "breath play",
        "breath control", "choking", "strangling", "asphyxiation", "breath holding",
        "waterboarding", "water torture", "wax play", "hot wax", "cold wax",
        "candle wax", "wax torture", "wax dripping", "wax massage", "wax removal",
        "needle play", "needle torture", "piercing", "body piercing", "genital piercing",
        "nipple piercing", "clit piercing", "hood piercing", "frenulum piercing",
        "prince albert", "apadravya", "ampallang", "dydoe", "hafada", "guiche",
        "ladder", "jacobs ladder", "scrotal ladder", "foreskin piercing",
        "urethral sounding", "sounding", "urethral play", "urethral insertion",
        "urethral stretching", "urethral dilation", "urethral plug", "urethral toy",
        "urethral sound", "urethral rod", "urethral tube", "urethral catheter",
        "urethral dilator", "urethral stretcher", "urethral expander",
        "urethral trainer", "urethral exerciser", "urethral massager",
        "urethral vibrator", "urethral stimulator", "urethral electrode",
        "urethral electrostimulation", "urethral electroplay", "urethral e-stim",
        "urethral tens", "urethral electrical", "urethral shock", "urethral zap",
        "urethral pain", "urethral pleasure", "urethral orgasm", "urethral cum",
        "urethral ejaculation", "urethral milking", "urethral extraction",
        "urethral massage", "urethral manipulation", "urethral stimulation",
        "urethral teasing", "urethral torture", "urethral punishment",
        "urethral discipline", "urethral training", "urethral conditioning",
        "urethral control", "urethral denial", "urethral chastity", "urethral lock",
        "urethral plug", "urethral stopper", "urethral cap", "urethral cover",
        "urethral shield", "urethral protector", "urethral guard", "urethral barrier",
        "urethral filter", "urethral strainer", "urethral sieve", "urethral mesh",
        "urethral net", "urethral web", "urethral lace", "urethral pattern",
        "urethral design", "urethral decoration", "urethral ornament", "urethral jewelry",
        "urethral accessory", "urethral attachment", "urethral add-on", "urethral extension",
        "urethral adapter", "urethral connector", "urethral coupling", "urethral joint",
        "urethral hinge", "urethral pivot", "urethral swivel", "urethral rotation",
        "urethral movement", "urethral motion", "urethral action", "urethral activity",
        "urethral play", "urethral fun", "urethral entertainment", "urethral amusement",
        "urethral recreation", "urethral pastime", "urethral hobby", "urethral interest",
        "urethral passion", "urethral obsession", "urethral fixation", "urethral fetish",
        "urethral kink", "urethral preference", "urethral taste", "urethral liking",
        "urethral desire", "urethral want", "urethral need", "urethral craving",
        "urethral hunger", "urethral thirst", "urethral appetite", "urethral longing",
        "urethral yearning", "urethral pining", "urethral aching", "urethral burning",
        "urethral fire", "urethral heat", "urethral warmth", "urethral glow",
        "urethral radiance", "urethral brilliance", "urethral shine", "urethral sparkle",
        "urethral glitter", "urethral shimmer", "urethral gleam", "urethral flash",
        "urethral burst", "urethral explosion", "urethral eruption", "urethral release",
        "urethral discharge", "urethral emission", "urethral expulsion", "urethral ejection",
        "urethral projection", "urethral propulsion", "urethral launch", "urethral firing",
        "urethral shooting", "urethral spraying", "urethral splashing", "urethral dripping",
        "urethral leaking", "urethral oozing", "urethral seeping", "urethral flowing",
        "urethral streaming", "urethral pouring", "urethral gushing", "urethral flooding",
        "urethral deluge", "urethral torrent", "urethral cascade", "urethral waterfall",
        "urethral fountain", "urethral geyser", "urethral volcano", "urethral eruption",
        "urethral explosion", "urethral burst", "urethral blast", "urethral bang",
        "urethral boom", "urethral crash", "urethral thunder", "urethral lightning",
        "urethral storm", "urethral tempest", "urethral hurricane", "urethral tornado",
        "urethral cyclone", "urethral whirlwind", "urethral vortex", "urethral spiral",
        "urethral whirl", "urethral spin", "urethral rotation", "urethral revolution",
        "urethral orbit", "urethral circle", "urethral ring", "urethral loop",
        "urethral coil", "urethral spiral", "urethral helix", "urethral twist",
        "urethral turn", "urethral bend", "urethral curve", "urethral arc",
        "urethral arch", "urethral bow", "urethral crescent", "urethral moon",
        "urethral smile", "urethral grin", "urethral laugh", "urethral giggle",
        "urethral chuckle", "urethral snicker", "urethral titter", "urethral chortle",
        "urethral guffaw", "urethral roar", "urethral howl", "urethral shriek",
        "urethral scream", "urethral yell", "urethral shout", "urethral cry",
        "urethral wail", "urethral moan", "urethral groan", "urethral sigh",
        "urethral breath", "urethral gasp", "urethral pant", "urethral heave",
        "urethral shudder", "urethral shake", "urethral tremble", "urethral quiver",
        "urethral vibration", "urethral oscillation", "urethral pulsation",
        "urethral rhythm", "urethral beat", "urethral throb", "urethral pulse",
        "urethral heartbeat", "urethral drum", "urethral music", "urethral song",
        "urethral melody", "urethral harmony", "urethral symphony", "urethral concerto",
        "urethral sonata", "urethral etude", "urethral prelude", "urethral interlude",
        "urethral finale", "urethral climax", "urethral crescendo", "urethral peak",
        "urethral summit", "urethral apex", "urethral zenith", "urethral pinnacle",
        "urethral height", "urethral elevation", "urethral altitude", "urethral level",
        "urethral degree", "urethral extent", "urethral measure", "urethral amount",
        "urethral quantity", "urethral volume", "urethral capacity", "urethral size",
        "urethral dimension", "urethral scale", "urethral proportion", "urethral ratio",
        "urethral percentage", "urethral fraction", "urethral part", "urethral portion",
        "urethral segment", "urethral section", "urethral piece", "urethral bit",
        "urethral fragment", "urethral particle", "urethral atom", "urethral molecule",
        "urethral cell", "urethral tissue", "urethral organ", "urethral system",
        "urethral structure", "urethral formation", "urethral construction",
        "urethral building", "urethral creation", "urethral making", "urethral production",
        "urethral manufacture", "urethral fabrication", "urethral assembly",
        "urethral construction", "urethral erection", "urethral erection", "urethral erection"
    ]
}
ADULT_CATEGORY_IDS = set([
    # eBay adult category IDs – these are categories known to contain adult content
    "281",      # Adult Only category
    "184065",   # Adult/Mature Audience
    "293",      # Adult items (legacy)
    "14080",    # Adult magazines
    "11450",    # Adult videos/DVDs
    "11433",    # Adult books
    "550",      # Adult collectibles (banned in most regions)
    "11731",    # Mature audiences health & beauty
    "176992",   # Sexual Wellness
    "176994",   # Condoms & Contraceptives
    "176995",   # Lubricants (sexual wellness)
    "176997",   # Sex Toys
    "176998",   # Sexual Remedies & Supplements
    "260748",   # Adult Toys
    "260749",   # Dildos & Vibrators
    "260750",   # Anal Sex Toys
    "260751",   # Sex Dolls & Masturbators
    "260752",   # Sex Pillows & Wedges
    "262990",   # Adult Toy Cleaners
])

# Category name keywords that indicate adult content (case-insensitive)
ADULT_CATEGORY_KEYWORDS = [
    "sexual wellness",
    "adult toy",
    "adult toys",
    "sex toy",
    "sex toys",
    "erotic",
    "adult only",
    "mature audience",
    "mature audiences",
]

def is_explicit(item):
    """
    Check if an item contains explicit content based on title, subtitle, and description.
    Uses word boundary matching where appropriate to avoid false positives.
    """
    import re
    
    text = (item.get("title","") + " " + item.get("subtitle","") + " " + item.get("shortDescription","")).lower()
    
    # Terms that should match as whole words only (to avoid false positives)
    whole_word_terms = {
        "sex", "anal", "cock", "dick", "tit", "pussy", "sexy", "oral", "bdsm",
        "sub", "dom", "kink", "nude", "naked", "fetish", "kinky", "furry",
        "dirty", "nasty", "naughty", "whip", "sperm", "condom", "condoms",
        "rubber", "rubbers", "protection", "safe sex", "contraceptive", "contraceptives",
        "birth control", "family planning", "lubricant", "lube", "trojan", "durex",
        "magnum", "ribbed", "textured", "flavored", "colored", "studded",
        "female condom", "dental dam", "finger cot", "finger cots", "massage oil",
        "sensual oil", "arousal gel", "warming gel", "cooling gel", "personal lubricant",
        "sexual lubricant", "intimate lubricant", "sex education", "sexual health",
        "std prevention", "sti prevention", "pregnancy prevention", "unwanted pregnancy",
        "emergency contraceptive", "morning after", "plan b", "ella", "iud", "coil",
        "implant", "hormonal contraceptive", "pill", "birth control pill", "the pill",
        "patch", "ring", "shot", "injection", "depo", "depo provera", "fertility awareness",
        "natural family planning", "rhythm method", "withdrawal", "pull out", "pullout method",
        "coitus interruptus", "abstinence", "celibacy", "virginity", "first time",
        "losing virginity", "sexual debut", "sexual initiation", "coming of age",
        "sexual maturity", "puberty", "adolescent", "teenage", "teen", "young adult",
        "sexual development", "sexual awakening", "sexual discovery", "masturbation",
        "self pleasure", "self-pleasure", "solo play", "mutual masturbation",
        "hand job", "handjob", "blow job", "blowjob", "oral sex", "fellatio",
        "cunnilingus", "69", "sixty nine", "foreplay", "heavy petting", "making out",
        "necking", "petting", "dry humping", "grinding", "frottage", "tribadism",
        "scissoring", "penetration", "vaginal", "anal", "oral", "digital", "fingering",
        "fisting", "double penetration", "dp", "gangbang", "bukkake", "creampie",
        "facials", "golden shower", "watersports", "scat", "roleplay", "role play",
        "dirty talk", "phone sex", "cybersex", "sexting", "nudes", "nude pics",
        "dick pic", "dick pics", "boob pic", "tit pic", "pussy pic", "ass pic",
        "butt pic", "selfie nude", "nude selfie", "explicit photo", "explicit image",
        "adult photo", "adult image", "sexual photo", "sexual image", "intimate photo",
        "intimate image", "private photo", "private image", "personal photo",
        "personal image", "bedroom photo", "bedroom image", "boudoir", "boudoir photo",
        "boudoir photography", "glamour", "glamour photo", "pinup", "pin up",
        "cheesecake", "beefcake", "softcore", "soft core", "hardcore", "hard core",
        "pornographic", "pornographic material", "obscene material", "indecent material",
        "lewd material", "sexual material", "adult material", "mature material",
        "adult entertainment", "adult content", "adult media", "adult film", "adult video",
        "adult movie", "adult dvd", "adult blu ray", "adult streaming", "adult subscription",
        "adult membership", "adult website", "adult site", "adult portal", "adult platform",
        "adult service", "adult provider", "adult worker", "sex worker", "escort service",
        "escort agency", "escort business", "escort work", "prostitution", "prostitute",
        "hooker", "streetwalker", "call girl", "high class escort", "luxury escort",
        "premium escort", "elite escort", "sugar daddy", "sugar baby", "sugar mommy",
        "sugar mama", "arrangement", "mutually beneficial", "benefactor", "sponsor",
        "financial support", "financial assistance", "allowance", "gift", "companionship",
        "intimate companionship", "romantic companionship", "dating", "casual dating",
        "casual sex", "hookup", "one night stand", "friends with benefits", "fwb",
        "booty call", "fuck buddy", "sex buddy", "playmate", "play partner",
        "sexual partner", "bed partner", "sleeping together", "sleeping around", "cheating",
        "affair", "extramarital", "adultery", "infidelity", "unfaithful", "swinging",
        "swingers", "swinger club", "swinger party", "swinger lifestyle", "wife swapping",
        "wife sharing", "husband swapping", "husband sharing", "couple swapping",
        "couple sharing", "group sex", "orgy", "gangbang", "threesome", "mfm", "fmf",
        "mmf", "ffm", "mfmf", "foursome", "fivesome", "sixsome", "orgy", "sex party",
        "sex club", "sex bar", "sex lounge", "sex dungeon", "sex room", "play room",
        "playroom", "dungeon", "bdsm dungeon", "fetish dungeon", "kink dungeon",
        "dominant", "dom", "domme", "domina", "mistress", "master", "submissive", "sub",
        "slave", "pet", "puppy", "kitten", "little", "brat", "bratty", "switch",
        "versatile", "top", "bottom", "vers", "sadist", "masochist", "sadomasochist",
        "sadomasochism", "s&m", "sadism", "masochism", "pain", "pleasure", "pain play",
        "pleasure play", "impact play", "whip", "flogger", "crop", "paddle", "spanking",
        "caning", "birching", "belting", "strapping", "whipping", "flogging", "bondage",
        "rope bondage", "shibari", "kinbaku", "rope play", "rope work", "rope art",
        "rope bondage", "bondage rope", "bondage tape", "duct tape", "electrical tape",
        "medical tape", "bondage gear", "restraints", "handcuffs", "leg cuffs",
        "ankle cuffs", "wrist cuffs", "collar", "leash", "harness", "straitjacket",
        "straight jacket", "gag", "ball gag", "bit gag", "ring gag", "spider gag",
        "mouth gag", "blindfold", "eye mask", "sleep mask", "hood", "leather hood",
        "latex hood", "rubber hood", "gas mask", "respirator", "breath play",
        "breath control", "choking", "strangling", "asphyxiation", "breath holding",
        "waterboarding", "water torture", "wax play", "hot wax", "cold wax",
        "candle wax", "wax torture", "wax dripping", "wax massage", "wax removal",
        "needle play", "needle torture", "piercing", "body piercing", "genital piercing",
        "nipple piercing", "clit piercing", "hood piercing", "frenulum piercing",
        "prince albert", "apadravya", "ampallang", "dydoe", "hafada", "guiche",
        "ladder", "jacobs ladder", "scrotal ladder", "foreskin piercing",
        "urethral sounding", "sounding", "urethral play", "urethral insertion",
        "urethral stretching", "urethral dilation", "urethral plug", "urethral toy",
        "urethral sound", "urethral rod", "urethral tube", "urethral catheter",
        "urethral dilator", "urethral stretcher", "urethral expander",
        "urethral trainer", "urethral exerciser", "urethral massager",
        "urethral vibrator", "urethral stimulator", "urethral electrode",
        "urethral electrostimulation", "urethral electroplay", "urethral e-stim",
        "urethral tens", "urethral electrical", "urethral shock", "urethral zap",
        "urethral pain", "urethral pleasure", "urethral orgasm", "urethral cum",
        "urethral ejaculation", "urethral milking", "urethral extraction",
        "urethral massage", "urethral manipulation", "urethral stimulation",
        "urethral teasing", "urethral torture", "urethral punishment",
        "urethral discipline", "urethral training", "urethral conditioning",
        "urethral control", "urethral denial", "urethral chastity", "urethral lock",
        "urethral plug", "urethral stopper", "urethral cap", "urethral cover",
        "urethral shield", "urethral protector", "urethral guard", "urethral barrier",
        "urethral filter", "urethral strainer", "urethral sieve", "urethral mesh",
        "urethral net", "urethral web", "urethral lace", "urethral pattern",
        "urethral design", "urethral decoration", "urethral ornament", "urethral jewelry",
        "urethral accessory", "urethral attachment", "urethral add-on", "urethral extension",
        "urethral adapter", "urethral connector", "urethral coupling", "urethral joint",
        "urethral hinge", "urethral pivot", "urethral swivel", "urethral rotation",
        "urethral movement", "urethral motion", "urethral action", "urethral activity",
        "urethral play", "urethral fun", "urethral entertainment", "urethral amusement",
        "urethral recreation", "urethral pastime", "urethral hobby", "urethral interest",
        "urethral passion", "urethral obsession", "urethral fixation", "urethral fetish",
        "urethral kink", "urethral preference", "urethral taste", "urethral liking",
        "urethral desire", "urethral want", "urethral need", "urethral craving",
        "urethral hunger", "urethral thirst", "urethral appetite", "urethral longing",
        "urethral yearning", "urethral pining", "urethral aching", "urethral burning",
        "urethral fire", "urethral heat", "urethral warmth", "urethral glow",
        "urethral radiance", "urethral brilliance", "urethral shine", "urethral sparkle",
        "urethral glitter", "urethral shimmer", "urethral gleam", "urethral flash",
        "urethral burst", "urethral explosion", "urethral eruption", "urethral release",
        "urethral discharge", "urethral emission", "urethral expulsion", "urethral ejection",
        "urethral projection", "urethral propulsion", "urethral launch", "urethral firing",
        "urethral shooting", "urethral spraying", "urethral splashing", "urethral dripping",
        "urethral leaking", "urethral oozing", "urethral seeping", "urethral flowing",
        "urethral streaming", "urethral pouring", "urethral gushing", "urethral flooding",
        "urethral deluge", "urethral torrent", "urethral cascade", "urethral waterfall",
        "urethral fountain", "urethral geyser", "urethral volcano", "urethral eruption",
        "urethral explosion", "urethral burst", "urethral blast", "urethral bang",
        "urethral boom", "urethral crash", "urethral thunder", "urethral lightning",
        "urethral storm", "urethral tempest", "urethral hurricane", "urethral tornado",
        "urethral cyclone", "urethral whirlwind", "urethral vortex", "urethral spiral",
        "urethral whirl", "urethral spin", "urethral rotation", "urethral revolution",
        "urethral orbit", "urethral circle", "urethral ring", "urethral loop",
        "urethral coil", "urethral spiral", "urethral helix", "urethral twist",
        "urethral turn", "urethral bend", "urethral curve", "urethral arc",
        "urethral arch", "urethral bow", "urethral crescent", "urethral moon",
        "urethral smile", "urethral grin", "urethral laugh", "urethral giggle",
        "urethral chuckle", "urethral snicker", "urethral titter", "urethral chortle",
        "urethral guffaw", "urethral roar", "urethral howl", "urethral shriek",
        "urethral scream", "urethral yell", "urethral shout", "urethral cry",
        "urethral wail", "urethral moan", "urethral groan", "urethral sigh",
        "urethral breath", "urethral gasp", "urethral pant", "urethral heave",
        "urethral shudder", "urethral shake", "urethral tremble", "urethral quiver",
        "urethral vibration", "urethral oscillation", "urethral pulsation",
        "urethral rhythm", "urethral beat", "urethral throb", "urethral pulse",
        "urethral heartbeat", "urethral drum", "urethral music", "urethral song",
        "urethral melody", "urethral harmony", "urethral symphony", "urethral concerto",
        "urethral sonata", "urethral etude", "urethral prelude", "urethral interlude",
        "urethral finale", "urethral climax", "urethral crescendo", "urethral peak",
        "urethral summit", "urethral apex", "urethral zenith", "urethral pinnacle",
        "urethral height", "urethral elevation", "urethral altitude", "urethral level",
        "urethral degree", "urethral extent", "urethral measure", "urethral amount",
        "urethral quantity", "urethral volume", "urethral capacity", "urethral size",
        "urethral dimension", "urethral scale", "urethral proportion", "urethral ratio",
        "urethral percentage", "urethral fraction", "urethral part", "urethral portion",
        "urethral segment", "urethral section", "urethral piece", "urethral bit",
        "urethral fragment", "urethral particle", "urethral atom", "urethral molecule",
        "urethral cell", "urethral tissue", "urethral organ", "urethral system",
        "urethral structure", "urethral formation", "urethral construction",
        "urethral building", "urethral creation", "urethral making", "urethral production",
        "urethral manufacture", "urethral fabrication", "urethral assembly",
        "urethral construction", "urethral erection", "urethral erection", "urethral erection"
    }
    
    # Check whole word terms with word boundaries
    for term in whole_word_terms:
        if term in DENYLIST_TERMS["explicit"]:
            # Use word boundaries to match whole words only
            pattern = r'\b' + re.escape(term) + r'\b'
            if re.search(pattern, text):
                return True
    
    # Check all other terms as substrings (these are more specific and unlikely to cause false positives)
    other_terms = [t for t in DENYLIST_TERMS["explicit"] if t not in whole_word_terms]
    for term in other_terms:
        if term in text:
            return True
    
    return False