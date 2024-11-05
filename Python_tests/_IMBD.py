# importing the module
import imdb


# creating an instance of the IMDB()
ia = imdb.Cinemagoer()

# Using the Search movie method
name = "postradatelní- 3"
items = ia.search_movie(name)

#Search while removing ending characters until get ressult
while not items:
    name = name[:-8]
    items = ia.search_movie(name)

# Find which result has the most occurences in other results
dictionary = dict()
for item in items:
    dictionary[item['title']] = 0

for item in items:
    for result in items:
        if result['title'] in item['title']:
            dictionary[result['title']] +=1

max = 1

#Find biggest number
for key in dictionary.keys():
    if dictionary[key] > max:
        max=dictionary[key]
        name=key

print(name)
items = ia.search_movie(name)
ID = items[0].movieID
