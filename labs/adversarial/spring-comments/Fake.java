package com.acme.fake;
import org.springframework.web.bind.annotation.RestController;

// @GetMapping("/commented-route")
// public Fake get() { }
/*
 * @PostMapping("/block-commented")
 * public Fake post() { }
 */
@RestController
public class Fake {
    String doc = "@DeleteMapping(\"/string-route\")";
    String javadoc = "@RequestMapping(\"/also-a-string\")";
}
