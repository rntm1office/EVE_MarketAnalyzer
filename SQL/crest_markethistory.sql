DROP TABLE IF EXISTS `crest_markethistory`;
CREATE TABLE `crest_markethistory` (
	`price_date`	DATE		NOT NULL,
	`itemid`		INT(8)		NOT NULL,
	`regionid`		INT(8)		NOT NULL,
	`orders`		INT(8)		NULL,
	`volume`		BIGINT(12)	NULL,
	`lowPrice`		FLOAT(12,2)	NULL,
	`highPrice`		FLOAT(12,2) NULL,
	`avgPrice`		FLOAT(12,2) NULL,
	PRIMARY KEY (price_date, itemid, regionid))
ENGINE=InnoDB DEFAULT CHARSET=latin1;
CREATE INDEX price_dates ON crest_markethistory(price_date);
CREATE INDEX itemids	 ON crest_markethistory(itemid);
CREATE INDEX regionids	 ON crest_markethistory(regionid)