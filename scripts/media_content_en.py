"""English student-production content bank (ELT / LVB class, target B1).

Per subject, three level tiers (low ~A2, mid ~B1, high ~B2). Each subject × tier
carries 4 short variants; the generator rotates variants by student index and
injects the student's first name so each copy differs. Written subjects -> the
"copy" text (answers / short essay). Oral subjects -> the spoken text (TTS+ASR).
"""

def tier_for(level: str) -> str:
    return {"A1": "low", "A2": "low", "B1": "mid", "B2": "high",
            "C1": "high", "C2": "high"}.get(level, "mid")


# ---------------------------------------------------------------- WRITTEN: READING comprehension (study of a text, short answers)
COMP_ECRITE = {
    "low": [
        "The text talks about the internet. The title is important because it gives "
        "the subject. The author wants to give his opinion. He uses simple words. "
        "I find the text easy to read and to understand.",
        "The document is an article. The author tells about a day at school. "
        "He describes the lessons and the friends. The tone is nice. "
        "I understand the main subject of the text.",
        "The title helps me to know what the text is about. The author talks about "
        "reading. He gives examples. The text is short. "
        "I can recognize some words of the vocabulary.",
        "The author explains why he likes school. He names some subjects. "
        "He talks about his friends too. The text is clear. "
        "I find the subject interesting for the students.",
    ],
    "mid": [
        "The text \"Screens and Us\" contrasts the advantages and the drawbacks of "
        "the digital world at school. The author adopts a balanced tone: he mentions "
        "the risks (addiction, distraction) but also the benefits (access to "
        "information, collaboration). His final thesis is that technology must be "
        "better controlled. The two-part structure, with a contrast marker such as "
        "\"yet\", makes the argumentation clearer.",
        "In this extract, the main character expresses an inner conflict. The author "
        "uses the present tense to give immediacy and expressive adjectives like "
        "\"huge\" and \"silent\" to build an atmosphere. The subtext, suggested by the "
        "final ellipsis, invites the reader to complete the meaning. The author's "
        "intention is to create empathy.",
        "The article is an argumentative text with an informative purpose. The author "
        "relies on figures and an expert's quote to strengthen his credibility. "
        "The rhetorical question in the second paragraph involves the reader. "
        "Overall, the register is fairly neutral, with a persuasive aim.",
        "The story follows a journey. The timeline marks the movement, alternating "
        "between descriptions (landscapes) and scenes (meetings). The lexical fields "
        "of space and movement structure the text. The author suggests a reflection "
        "on openness to others, carried by the final encounter.",
    ],
    "high": [
        "The text is an argumentative essay whose thesis - that digital surveillance "
        "undermines autonomy - is developed through a funnel structure: from a factual "
        "observation to a warning. The author combines the appeal to authority and a "
        "concession (\"we should not demonise it\") to anticipate the counter-argument. "
        "The tone oscillates between the didactic and the involved, reinforced by the "
        "lexical field of imprisonment (\"lock\", \"cage\"). The intention is clearly "
        "hortatory.",
        "The extract proceeds through anaphora, which paces the monologue and builds "
        "an escalation of anxiety. The author plays on the oxymoron \"chained freedom\" "
        "and a direct address to the reader to question his own habits. The open "
        "ending unbalances the lyrical register and forces reflection. The critical "
        "dimension on contemporary society dominates.",
        "This press document adopts an analytical angle: the author correlates three "
        "phenomena (urbanisation, remote work, isolation) and draws a transformation "
        "of social bonds. The argument, backed by data and an anecdote, leaves room "
        "for a nuance at the end (the hope of a \"renaissance\"). The funnel structure "
        "and the use of the conditional (\"could\") signal the epistemic caution of the "
        "author.",
        "The fiction text uses analepsis and prolepsis to place the action within its "
        "trajectory. Temporal deixis structures the narrative and the restricted "
        "internal focalisation limits the point of view to the character. The author "
        "builds suspense through an implicit subtext (the unread letter) whose "
        "deferred revelation creates the tension. The moral scope is social.",
    ],
}

# ---------------------------------------------------------------- WRITTEN: WRITING production (argumentative essay)
PROD_ECRITE = {
    "low": [
        "I think social networks are useful. With them, we talk to our friends. "
        "We can also watch videos and learn. But we must be careful, because we can "
        "lose time. In my opinion, we should use them without being too much. "
        "That is my opinion about social networks.",
        "Sport is important for me. I play football with my friends. "
        "Doing sport is good for the body and for the mind. It gives us a rhythm "
        "which pushes us. Even if it is sometimes tiring, I continue. "
        "I recommend sport to everybody, regularly.",
        "My town is nice because it has a park and a river. We walk there with the "
        "family on Sundays. The people are welcoming and like to talk. "
        "The shops are practical for the shopping. It is a good town "
        "to live in and to rest calmly.",
        "I like reading stories because they relax me and give me an escape. I read "
        "mostly before sleeping, in my bed, under the blanket. The characters often "
        "make me laugh. Reading is my biggest pleasure every week, I cannot live "
        "without it.",
    ],
    "mid": [
        "In my opinion, we should ban social networks for high school students, at "
        "least during lessons. First, the phone is a source of distraction that "
        "weakens concentration, and studies regularly confirm it. Second, the "
        "constant comparison on these platforms feeds a feeling of inferiority that "
        "can destabilise teenagers who are still finding themselves. It is not a "
        "matter of rejecting technology, but of reminding that a tool must remain a "
        "means, not an end in itself.",
        "Has remote working improved our working conditions? On the surface, it "
        "removes the commute and offers a certain flexibility of hours. "
        "However, it blurs the boundaries between the professional and the personal "
        "life: we still answer in the evening and we isolate ourselves more. "
        "In the long term, it is the collective presence, and therefore the "
        "cohesion, that suffers. I think we should rather look for a balance, "
        "without turning everything upside down at once.",
        "I support the idea that we should give the arts a bigger place at school. "
        "The musical or plastic experience develops imagination, reinforces "
        "personal expression and offers a safety valve for those who find "
        "science difficult. It is also a factor of inclusion: everyone is at "
        "their own level there. Finally, this openness better prepares, I believe, "
        "the citizens of tomorrow.",
        "Tourism development must remain reasonable. Of course, it brings in money "
        "and makes our regions known. But, if we are not careful, it destroys the "
        "landscapes and the ways of life it is actually showing. "
        "Over-tourism, in particular, exhausts the places and the inhabitants. "
        "We should therefore regulate it and value a softer, more local tourism.",
    ],
    "high": [
        "Widespread surveillance, in exchange for a feeling of security, questions the "
        "very notion of freedom. At first sight, it seems harmless: one more camera, "
        "one more sensor. Yet, the sum of these points of vigilance gradually draws a "
        "map of everyone's habits, a biography that we no longer control. The question "
        "is therefore not only technical, it is philosophical: on what basis does the "
        "authority compile our gestures? I defend the idea that security cannot "
        "justify that we silently give up our margin of autonomy.",
        "It seems to me that school success must no longer be reduced to the grade. "
        "For a long time, the system has worked like a timed race: measure, rank, "
        "sanction. Yet this logic reduces the child to a result and forgets the "
        "skills that matter, namely learning to learn, cooperating, daring to make a "
        "mistake. Rather than a thermometer, school would do better to become a "
        "garden: we do not look for the performance of the moment but the slow, "
        "uneven growth of every pupil.",
        "The city is not only a place where we live; it is the continuous product of "
        "decisions that we entrust to a few. Yet, when the city is designed without "
        "its inhabitants, it ends up escaping them. The square, the park, the street "
        "corner are as many grounds on which belonging is played out, concretely. "
        "It therefore seems essential to me to reintroduce the citizen debate as "
        "close to the places as possible, otherwise we build functional sets that "
        "are never truly inhabited.",
        "Can we still think of work without conceiving it as a burden? The idea that "
        "effort must be bitter inherits from a moral imaginary that associates value "
        "and suffering. Yet the forms of work have changed, and some jobs give back "
        "meaning, pride, even pleasure. Refusing to question our representations is "
        "letting them impose themselves. We need, in my view, to resume a frank "
        "discussion about what we truly expect of this time in which we spend such a "
        "large part of our lives.",
    ],
}

# ---------------------------------------------------------------- ORAL: LISTENING comprehension (dictation / reading aloud + short answers)
COMP_ORALE = {
    "low": [
        "The school. The park. The market. The library. The classroom. The friends. "
        "The books. The toys. The playground. The clock. The board. The exercise books.",
        "Hello. My name is {name}. I go to the school in the centre. I love school. "
        "I love the break time. I love reading. I have many friends. "
        "That is all. Thank you for listening.",
        "The sun. The rain. The wind. The snow. The summer. The winter. The spring. "
        "The autumn. The colours. The seasons that change during the year.",
        "My family. My father. My mother. My brothers. My sister. The grandparents. "
        "The neighbours. Everybody is important for me.",
    ],
    "mid": [
        "The document I have just listened to talks about the advantages and the "
        "drawbacks of the digital world at school. First, it evokes the access to "
        "information and the collaboration between pupils. Then, it deals with the "
        "risks: addiction, distraction, lack of concentration. "
        "Finally, it proposes to better control the use. That is my summary of the "
        "document.",
        "The extract describes a departure on a journey. The character prepares his "
        "suitcases, watches the town from far away, then gets on the train. The "
        "atmosphere is poetic and melancholy. We feel an attachment, a nostalgia. "
        "The author suggests that leaving is also a little bit losing something. "
        "That is what I keep from the reading aloud.",
        "The article analyses the consequences of remote working. The strong points "
        "are the flexibility and the removal of the journeys. The weak points concern "
        "isolation, the difficulty to disconnect, and the team cohesion. "
        "The author concludes that we must find a just middle. "
        "So here are my answers to the comprehension questions.",
        "The story presents an encounter in a park. Two characters meet, talk about "
        "their memories, and share a silence. The text insists on the movement and "
        "the landscapes. The author evokes the openness to others and the importance "
        "of human bonds. That is what I understood from the listening of the document.",
    ],
    "high": [
        "The text I have just read aloud defends the thesis that digital surveillance "
        "compromises individual autonomy. The author structures his reasoning in a "
        "funnel: from a factual observation, he slips towards the warning. He "
        "combines the appeal to authority, an anticipated concession, and a marked "
        "vocabulary with the field of imprisonment. The intention is hortatory, "
        "almost lyrical. That is what I keep from the analysis.",
        "The extract proceeds by anaphora and builds an escalation of the anxiety. "
        "The author plays on the oxymoron \"chained freedom\" and addresses the reader "
        "to question his own habits. The open ending unbalances the register and "
        "forces the reflection. The critical scope on contemporary society dominates "
        "the whole. I therefore summarise the listening of the text this way.",
        "The press document adopts an analytical angle: it correlates urbanisation, "
        "remote working and isolation, and draws a transformation of the social bonds. "
        "The argument is backed by data and an anecdote, and leaves room for a nuance "
        "at the end. The use of the conditional signals the caution of the author. "
        "Here are the answers to the comprehension questions that were asked.",
        "The fiction text resorts to analepsis and prolepsis to place the action in "
        "its trajectory. The internal focalisation restricts the point of view to the "
        "character, and the implicit subtext creates the suspense. The social "
        "dimension of the morality dominates. That is, according to me, the "
        "understanding that I propose of the listened document.",
    ],
}

# ---------------------------------------------------------------- ORAL: SPEAKING production (argumentative talk)
PROD_ORALE = {
    "low": [
        "Good morning. Today, I will talk about my favourite sport, football. "
        "I love football because I play with my friends in the park. "
        "We run, we have fun, we laugh a lot. Sport is important "
        "to be in good shape and to have health. That is why I play every "
        "Saturday in the courtyard of the quarter. That is all, thank you.",
        "Good morning everybody. I will tell you about my holidays. We went "
        "to the sea with my family. I loved playing in the water and building "
        "sand castles. We also ate very nice ice creams. "
        "It was really a very beautiful week. Thank you for listening.",
        "I would like to talk about my town. It is small but pretty. There is "
        "a park, a river, and many trees. The people are very "
        "kind and welcoming. We like to walk there on the weekend. "
        "It is a town where it is nice to live and to rest. Thank you.",
        "Today, I will talk about my favourite books. I really "
        "like stories of fairy tales and monsters. I read mostly before sleeping, "
        "in my bed, under the blanket. The characters are funny and "
        "amusing. It is my biggest pleasure every week. That is all, thank you.",
    ],
    "mid": [
        "Good morning. I will present my talk about social networks for teenagers. "
        "I think that we should control them more. First, excessive use weakens "
        "concentration and the quality of sleep: we scroll late in the evening, we "
        "answer in the middle of the night. Second, the constant comparison on these "
        "platforms feeds a feeling of inferiority that can destabilise young people. "
        "It is not a question of rejecting the digital, but of using it without "
        "becoming dependent on it. That is all, thank you for your attention.",
        "Good morning. My subject today is remote working. On the one hand, it "
        "removes the commute and offers an appreciable flexibility of hours. "
        "On the other hand, it blurs the limits between work and personal life: we "
        "still answer in the evening and we isolate ourselves. In the long term, it "
        "is the team cohesion that suffers. I believe that we must look for a "
        "balance, without turning everything upside down at once. Thank you for "
        "listening.",
        "Good morning. I would like to say why we should give the arts a bigger place "
        "at school. The musical or plastic experience develops imagination and "
        "reinforces personal expression. It also offers a valve for those who find "
        "science difficult. It is finally a factor of inclusion, because everyone is "
        "at their own level there. I think that it better prepares the citizens of "
        "tomorrow. That is all, thank you.",
        "Good morning. I will talk about tourism and what it brings us. "
        "It brings in money, it makes our regions known. But, if we are not "
        "careful, it destroys the landscapes it is actually showing. "
        "Over-tourism exhausts the places and the inhabitants. We should therefore "
        "regulate it and value a softer, more local tourism. That is my opinion. "
        "Thank you for listening.",
    ],
    "high": [
        "Good morning. Today, I propose a reflection on digital surveillance. "
        "At first sight, it seems harmless: one more camera, one more sensor. Yet, "
        "the sum of these points of vigilance draws a map of our habits, a biography "
        "that we no longer control. The question is therefore not only technical, it "
        "is philosophical: on what basis does the authority compile our gestures? I "
        "defend the idea that security cannot justify that we abandon, silently, our "
        "margin of autonomy. That is all, thank you for your attention.",
        "Good morning. I would like to question the notion of school success. For a "
        "long time, the system has worked like a timed race: to measure, to rank, to "
        "sanction. Yet this logic reduces the pupil to a result and forgets the "
        "skills that truly matter: to learn how to learn, to cooperate, to dare the "
        "mistake. Rather than a thermometer, school would do better to become a "
        "garden: we do not look for the performance of the moment, but the slow and "
        "uneven growth of every pupil. Thank you for following.",
        "Good morning. The city is not only a place where we live; it is the "
        "continuous product of decisions that we entrust to a few. Yet, when the "
        "city is designed without its inhabitants, it ends up escaping them. The "
        "square, the park, the street corner are as many grounds on which the feeling "
        "of belonging is played out, in a very concrete way. It therefore seems "
        "essential to me to reintroduce the citizen debate as close to the places as "
        "possible. Otherwise, we build functional sets that are never truly inhabited. "
        "That is all, thank you.",
        "Good morning. Can we still think of work without conceiving it as a burden? "
        "The idea that effort must be bitter inherits from a moral imaginary that "
        "associates value and suffering. Yet the forms of work have changed, and some "
        "jobs give back meaning, pride, even pleasure. Refusing to question our "
        "representations is letting them impose themselves. We need, in my view, to "
        "resume a frank discussion about what we truly expect of this time in which we "
        "spend such a large part. That is all, thank you for listening.",
    ],
}


CONTENT = {
    "comp-ecrite": COMP_ECRITE,
    "prod-ecrite": PROD_ECRITE,
    "comp-orale":  COMP_ORALE,
    "prod-orale":  PROD_ORALE,
}


def pick_content(subject_key: str, level: str, student_idx: int,
                 first_name: str | None = None) -> str:
    tier = tier_for(level)
    variants = CONTENT[subject_key][tier]
    text = variants[student_idx % len(variants)]
    if first_name:
        text = text.replace("{name}", first_name)
    return text
