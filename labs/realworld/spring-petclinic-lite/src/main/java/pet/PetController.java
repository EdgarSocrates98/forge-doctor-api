import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping("/pets")
public class PetController {
    @GetMapping("/{petId}")
    public String show(@PathVariable int petId) { return "pet"; }
    @PostMapping("/{petId}/edit")
    public String edit(@PathVariable int petId) { return "form"; }
    @RequestMapping(value = "/owners/{ownerId}", method = RequestMethod.GET)
    public String owner(@PathVariable int ownerId) { return "owner"; }
}
