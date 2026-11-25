"""Sample problems used by `python manage.py seed_problems`.

Every problem reads from standard input and prints to standard output.
Each test case is (input_data, expected_output, is_sample).
"""

SEED_TOPICS = [
    {
        "name": "Arrays",
        "order": 1,
        "subtopics": [
            {
                "name": "Traversal and Counting",
                "order": 1,
                "problems": [
                    {
                        "title": "Sum of Array",
                        "difficulty": "Easy",
                        "statement": (
                            "Given an array of integers, print the sum of all its elements.\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n space-separated integers.\n\n"
                            "Output:\nA single integer, the sum of the array.\n\n"
                            "Constraints:\n1 <= n <= 1000\n-1000 <= each element <= 1000"
                        ),
                        "tests": [
                            ("5\n1 2 3 4 5", "15", True),
                            ("3\n-2 -3 -5", "-10", True),
                            ("1\n7", "7", False),
                            ("4\n0 0 0 0", "0", False),
                            ("6\n1000 -1000 500 500 -250 250", "1000", False),
                        ],
                    },
                    {
                        "title": "Second Largest Element",
                        "difficulty": "Medium",
                        "statement": (
                            "Print the second largest distinct value in the array. "
                            "The array always has at least two different values.\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n space-separated integers.\n\n"
                            "Output:\nA single integer, the second largest distinct value.\n\n"
                            "Constraints:\n2 <= n <= 1000\n-10000 <= each element <= 10000"
                        ),
                        "tests": [
                            ("5\n3 1 4 1 5", "4", True),
                            ("4\n10 10 9 8", "9", True),
                            ("2\n-5 -1", "-5", False),
                            ("6\n7 7 7 2 7 7", "2", False),
                            ("5\n-1 -2 -3 -4 -5", "-2", False),
                        ],
                    },
                ],
            },
            {
                "name": "Two Pointers",
                "order": 2,
                "problems": [
                    {
                        "title": "Reverse an Array",
                        "difficulty": "Easy",
                        "statement": (
                            "Print the elements of the array in reverse order, separated by single spaces.\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n space-separated integers.\n\n"
                            "Output:\nThe n integers in reverse order on one line.\n\n"
                            "Constraints:\n1 <= n <= 1000\n-1000 <= each element <= 1000"
                        ),
                        "tests": [
                            ("5\n1 2 3 4 5", "5 4 3 2 1", True),
                            ("1\n9", "9", True),
                            ("4\n-1 0 2 -3", "-3 2 0 -1", False),
                            ("3\n8 8 1", "1 8 8", False),
                        ],
                    },
                    {
                        "title": "Pair With Given Sum",
                        "difficulty": "Medium",
                        "statement": (
                            "You are given an array sorted in ascending order and a target number. "
                            "Print YES if two elements at different positions add up to the target, "
                            "otherwise print NO. (Hint: use two pointers, one at each end.)\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n integers in ascending order.\n"
                            "Line 3: the target integer.\n\n"
                            "Output:\nYES or NO.\n\n"
                            "Constraints:\n1 <= n <= 1000\n-10000 <= each element and target <= 10000"
                        ),
                        "tests": [
                            ("6\n1 3 4 6 8 11\n10", "YES", True),
                            ("4\n1 2 3 9\n8", "NO", True),
                            ("2\n5 5\n10", "YES", False),
                            ("1\n5\n10", "NO", False),
                            ("5\n-4 -1 0 3 7\n3", "YES", False),
                        ],
                    },
                ],
            },
        ],
    },
    {
        "name": "Strings",
        "order": 2,
        "subtopics": [
            {
                "name": "Basic Operations",
                "order": 1,
                "problems": [
                    {
                        "title": "Palindrome Check",
                        "difficulty": "Easy",
                        "statement": (
                            "A palindrome reads the same from left to right and right to left. "
                            "Print YES if the given string is a palindrome, otherwise print NO.\n\n"
                            "Input:\nOne line with a string of lowercase letters.\n\n"
                            "Output:\nYES or NO.\n\n"
                            "Constraints:\n1 <= length of the string <= 1000"
                        ),
                        "tests": [
                            ("level", "YES", True),
                            ("coding", "NO", True),
                            ("a", "YES", False),
                            ("abba", "YES", False),
                            ("abca", "NO", False),
                        ],
                    },
                    {
                        "title": "Reverse Words in a Sentence",
                        "difficulty": "Medium",
                        "statement": (
                            "Print the words of the sentence in reverse order, separated by a single space. "
                            "Extra spaces at the start, at the end or between words must be ignored.\n\n"
                            "Input:\nOne line with a sentence of lowercase words separated by spaces.\n\n"
                            "Output:\nThe words in reverse order on one line.\n\n"
                            "Constraints:\n1 <= number of words <= 100"
                        ),
                        "tests": [
                            ("the sky is blue", "blue is sky the", True),
                            ("hello", "hello", True),
                            ("  one   two  three ", "three two one", False),
                            ("a b", "b a", False),
                        ],
                    },
                ],
            },
            {
                "name": "Frequency and Counting",
                "order": 2,
                "problems": [
                    {
                        "title": "Count Vowels",
                        "difficulty": "Easy",
                        "statement": (
                            "Print how many vowels (a, e, i, o, u) the line contains.\n\n"
                            "Input:\nOne line with lowercase letters and spaces.\n\n"
                            "Output:\nA single integer, the number of vowels.\n\n"
                            "Constraints:\n1 <= length of the line <= 1000"
                        ),
                        "tests": [
                            ("hello world", "3", True),
                            ("rhythm", "0", True),
                            ("aeiou", "5", False),
                            ("data structures and algorithms", "9", False),
                        ],
                    },
                    {
                        "title": "Longest Substring Without Repeating Characters",
                        "difficulty": "Hard",
                        "statement": (
                            "A substring is a block of consecutive characters. "
                            "Print the length of the longest substring in which no character appears twice. "
                            "(Hint: use a sliding window and a set or a dictionary.)\n\n"
                            "Input:\nOne line with a string of lowercase letters.\n\n"
                            "Output:\nA single integer, the length of that substring.\n\n"
                            "Constraints:\n1 <= length of the string <= 10000"
                        ),
                        "tests": [
                            ("abcabcbb", "3", True),
                            ("bbbbb", "1", True),
                            ("pwwkew", "3", False),
                            ("abcdef", "6", False),
                            ("dvdf", "3", False),
                        ],
                    },
                ],
            },
        ],
    },
    {
        "name": "Searching and Sorting",
        "order": 3,
        "subtopics": [
            {
                "name": "Binary Search",
                "order": 1,
                "problems": [
                    {
                        "title": "Binary Search",
                        "difficulty": "Easy",
                        "statement": (
                            "You are given an array sorted in ascending order with no repeated values. "
                            "Print the 0-based position of the target, or -1 if it is not in the array.\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n integers in ascending order.\n"
                            "Line 3: the target integer.\n\n"
                            "Output:\nA single integer: the position of the target or -1.\n\n"
                            "Constraints:\n1 <= n <= 10000\n-100000 <= each element and target <= 100000"
                        ),
                        "tests": [
                            ("5\n2 4 6 8 10\n8", "3", True),
                            ("5\n2 4 6 8 10\n5", "-1", True),
                            ("1\n3\n3", "0", False),
                            ("6\n-9 -3 0 4 11 20\n-9", "0", False),
                            ("6\n-9 -3 0 4 11 20\n20", "5", False),
                        ],
                    },
                    {
                        "title": "Search in Rotated Sorted Array",
                        "difficulty": "Hard",
                        "statement": (
                            "An array that was sorted in ascending order (no repeated values) has been rotated "
                            "at an unknown position, for example 0 1 2 4 5 6 7 became 4 5 6 7 0 1 2. "
                            "Print the 0-based position of the target, or -1 if it is not present. "
                            "Try to solve it in O(log n) time.\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: the n integers of the rotated array.\n"
                            "Line 3: the target integer.\n\n"
                            "Output:\nA single integer: the position of the target or -1.\n\n"
                            "Constraints:\n1 <= n <= 10000\n-100000 <= each element and target <= 100000"
                        ),
                        "tests": [
                            ("7\n4 5 6 7 0 1 2\n0", "4", True),
                            ("7\n4 5 6 7 0 1 2\n3", "-1", True),
                            ("1\n1\n1", "0", False),
                            ("5\n3 4 5 1 2\n1", "3", False),
                            ("4\n1 2 3 4\n4", "3", False),
                        ],
                    },
                ],
            },
            {
                "name": "Sorting",
                "order": 2,
                "problems": [
                    {
                        "title": "Merge Two Sorted Arrays",
                        "difficulty": "Medium",
                        "statement": (
                            "Merge two arrays that are each sorted in ascending order into one sorted array.\n\n"
                            "Input:\nLine 1: an integer n, the size of the first array.\n"
                            "Line 2: the n integers of the first array.\n"
                            "Line 3: an integer m, the size of the second array.\n"
                            "Line 4: the m integers of the second array.\n\n"
                            "Output:\nAll n + m integers in ascending order, separated by single spaces.\n\n"
                            "Constraints:\n1 <= n, m <= 1000\n-10000 <= each element <= 10000"
                        ),
                        "tests": [
                            ("3\n1 3 5\n3\n2 4 6", "1 2 3 4 5 6", True),
                            ("2\n1 1\n3\n1 2 2", "1 1 1 2 2", True),
                            ("1\n5\n1\n-5", "-5 5", False),
                            ("4\n-3 -1 0 2\n2\n-2 3", "-3 -2 -1 0 2 3", False),
                        ],
                    },
                    {
                        "title": "Count Inversions",
                        "difficulty": "Hard",
                        "statement": (
                            "An inversion is a pair of positions i < j where the value at i is greater than "
                            "the value at j. Print the number of inversions in the array. "
                            "(Hint: a modified merge sort can count them faster than checking every pair.)\n\n"
                            "Input:\nLine 1: an integer n, the number of elements.\n"
                            "Line 2: n space-separated integers.\n\n"
                            "Output:\nA single integer, the number of inversions.\n\n"
                            "Constraints:\n1 <= n <= 1000\n-10000 <= each element <= 10000"
                        ),
                        "tests": [
                            ("5\n2 4 1 3 5", "3", True),
                            ("4\n1 2 3 4", "0", True),
                            ("4\n4 3 2 1", "6", False),
                            ("1\n10", "0", False),
                            ("6\n5 5 4 4 3 3", "12", False),
                        ],
                    },
                ],
            },
        ],
    },
]
