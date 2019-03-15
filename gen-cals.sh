#!/usr/bin/bash

./cal.py | while IFS= read -r line; do
	./cal.py --cals "$line" > "$line.ical"
done
