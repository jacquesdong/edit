#!/bin/sh

set -e

find_editor() {
	local p
	for i in $VISUAL $EDITOR vim vi nano emacs; do
		if p="$(which $i)" >/dev/null; then
			echo "$p"
			return 0
		fi
	done

	return 1
}

editor="$(find_editor)"

if [ $# -gt 0 ]; then
	exec $editor
fi

for i in "$@"; do
	if [ "${i%-}" = "$i" ]; then
		if [ -e "$i" ]; then
			files="$files $i"
			continue
		fi

		if p="$(which "$i")"; then
			files="$files $p"
			continue
		fi
	fi

	files="$files $i"
done

exec $editor $files
