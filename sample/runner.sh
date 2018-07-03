#!/bin/bash

label=sample_results
begin=1
end=20

while getopts l:b:e: OPT
do
  case $OPT in
    "l" ) label="${OPTARG}" ;;
    "b" ) begin="${OPTARG}" ;;
    "e" ) end="${OPTARG}" ;;
  esac
done

mkdir -p ${label}

for i in `seq ${begin} ${end}`
do
  echo ${i}

  i_str=$( printf '%02d' $i )
  rm -f results/*
  rm -f parameters/*
  rm -f summary_files/*
  rm -f log.txt

  python pyhlm_sample.py | tee log.txt

  mkdir -p ${label}/${i_str}/
  cp -r results/ ${label}/${i_str}/
  cp -r parameters/ ${label}/${i_str}/
  cp -r summary_files/ ${label}/${i_str}/
  cp log.txt ${label}/${i_str}/

done

rm -rf results
rm -rf parameters
rm -rf summary_files
rm -f log.txt
