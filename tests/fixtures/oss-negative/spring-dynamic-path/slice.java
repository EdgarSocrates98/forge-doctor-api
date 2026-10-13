package com.example.pets;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
@RequestMapping("/pets")
public class DynamicPetController {

    private static final String OWNER = "/{ownerId}";

    @GetMapping(value = OWNER + "/edit")
    public String editForm() {
        return "pets/edit";
    }

    @GetMapping("${petclinic.legacy-path}")
    public String legacyAlias() {
        return "pets/legacy";
    }
}
