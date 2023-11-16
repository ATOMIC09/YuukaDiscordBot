import random
import requests


# Draw
def state1():
    print("  _______")
    print(" |/      |")
    print(" |")
    print(" |")
    print(" |")
    print(" |")
    print("_|___")

def state2():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |")
    print(" |")
    print(" |")
    print("_|___")

def state3():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |       |")
    print(" |")
    print(" |")
    print("_|___")

def state4():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |      \|")
    print(" |")
    print(" |")
    print("_|___")

def state5():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |      \|/")
    print(" |")
    print(" |")
    print("_|___")


def state6():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |      \|/")
    print(" |       |")
    print(" |      /")
    print("_|___")

def state7():
    print("  _______")
    print(" |/      |")
    print(" |     (;-;)")
    print(" |      \|/")
    print(" |       |")
    print(" |      / \ ")
    print("_|___")

word_site = "https://www.mit.edu/~ecprice/wordlist.10000"

response = requests.get(word_site)
WORDS = response.content.splitlines()
word_selected = random.choice(WORDS).decode("utf-8")

alphabet_user = ""
already_ans = []
correct = 0
incorrect = 0

def check_letter():
    index = 0
    while index < len(word_selected):
        if word_selected[index] == alphabet_user:
            return index
        index = index + 1

def drawing():
    index = 0
    correct_index = check_letter()

    if incorrect == 0:
        state7()
    if incorrect == 1:
        state6()
    if incorrect == 2:
        state5()
    if incorrect == 3:
        state4()
    if incorrect == 4:
        state3()
    if incorrect == 5:
        state2()
    if incorrect == 6:
        state1()

    print("\nHint : ", end = "")

    while index < len(word_selected):
        if index == correct_index:
            print(alphabet_user, end="")
        else:
            if word_selected[index] in already_ans:
                print(word_selected[index], end="")
            else:
                print("_", end="")
        index = index + 1

drawing()
print("\n\n")
alphabet_user = input("Enter a letter: ")
if alphabet_user not in already_ans:
    already_ans.append(alphabet_user)

while alphabet_user != "0" and correct < len(word_selected) and incorrect < 6:
    for i in range(len(word_selected)): # เพราะอาจมีตัวอักษรซ้ำ
        if word_selected[i] == alphabet_user:
            correct = correct + 1
    if alphabet_user not in word_selected:
        incorrect = incorrect + 1

    drawing()
    print("\n\n")

    if correct != len(word_selected) and incorrect != 6:
        alphabet_user = input("Enter a letter: ")
        if alphabet_user not in already_ans:
            already_ans.append(alphabet_user)
    
drawing()
print("\n")
if correct == len(word_selected):
    print("🎊 You win! 🎉")
else:
    print("❌ You lose! 🗿")
print()